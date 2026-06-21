"""
跨轮检索器：语义检索历史 Turn 摘要。

Phase 3 核心组件：
- 将 TurnSummary 向量化存储
- 新 query 到来时检索语义相关的历史 Turn
- 将相关历史注入当前上下文，打破滑动窗口的信息边界

实现：复用 ChromaDB + DashScopeEmbeddings（与 RAG 引擎一致），
使用独立的 collection "turn_memory"。
"""

import os
import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from app.utils.summarizer import TurnSummary
from app.utils.token_counter import count_tokens


# ─── 数据模型 ───

@dataclass
class RetrievedTurn:
    """检索到的历史 Turn 及其相关性。"""
    turn_id: str
    turn_number: int
    query_gist: str
    key_facts: List[str]
    conclusions: List[str]
    topic_tags: List[str]
    importance_score: float
    relevance_score: float = 0.0  # 相似度分数
    summary_text: str = ""        # 用于展示的摘要文本

    @property
    def display_text(self) -> str:
        """用于注入 Prompt 的展示文本。"""
        parts = [
            f"## 相关历史研究 (Turn {self.turn_number}, 相关度: {self.relevance_score:.2f})",
            f"**问题**: {self.query_gist[:150]}",
        ]
        if self.key_facts:
            parts.append(f"**关键发现**: {'; '.join(self.key_facts[:3])}")
        if self.conclusions:
            parts.append(f"**结论**: {'; '.join(self.conclusions[:2])}")
        return "\n".join(parts)


@dataclass
class RetrievalResult:
    """检索结果。"""
    query: str
    retrieved_turns: List[RetrievedTurn] = field(default_factory=list)
    context_text: str = ""
    total_tokens: int = 0


# ─── CrossTurnRetriever ───

class CrossTurnRetriever:
    """
    跨轮语义检索器。

    用法:
        ctr = CrossTurnRetriever()

        # 索引一个 Turn 摘要
        ctr.index(summary)

        # 检索与新 query 相关的历史
        result = ctr.retrieve("量子计算的最新进展", top_k=3)

        # 将检索结果注入 Prompt
        prompt += result.context_text
    """

    # 存储 summary 的 ChromaDB collection 名称
    COLLECTION_NAME = "turn_memory"

    def __init__(self):
        self._embeddings = None
        self._vectorstore = None
        self._summaries: Dict[str, TurnSummary] = {}  # 本地缓存

    # ─── 初始化 ───

    def _get_embeddings(self):
        """懒加载 embedding 模型。"""
        if self._embeddings is None:
            try:
                from langchain_community.embeddings import DashScopeEmbeddings
                from app.core.config import settings
                self._embeddings = DashScopeEmbeddings(
                    model="text-embedding-v4",
                    dashscope_api_key=settings.require_dashscope_api_key(),
                )
            except Exception:
                # 降级到 HuggingFace
                from langchain_huggingface import HuggingFaceEmbeddings
                self._embeddings = HuggingFaceEmbeddings(
                    model_name="moka-ai/m3e-base"
                )
        return self._embeddings

    def _get_vectorstore(self):
        """懒加载 ChromaDB vector store（专用 collection）。"""
        if self._vectorstore is None:
            from langchain_community.vectorstores import Chroma

            # 与 RAG 引擎共用基础路径，但使用独立 collection
            persist_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "rag", "chroma_db_turns",
            )
            os.makedirs(persist_dir, exist_ok=True)

            embeddings = self._get_embeddings()

            try:
                self._vectorstore = Chroma(
                    collection_name=self.COLLECTION_NAME,
                    embedding_function=embeddings,
                    persist_directory=persist_dir,
                )
            except Exception:
                # 全新创建
                self._vectorstore = Chroma(
                    collection_name=self.COLLECTION_NAME,
                    embedding_function=embeddings,
                    persist_directory=persist_dir,
                )

        return self._vectorstore

    # ─── 索引 ───

    def index(self, summary: TurnSummary) -> bool:
        """
        将 TurnSummary 索引到向量存储。

        Args:
            summary: TurnSummary 对象

        Returns:
            是否索引成功
        """
        try:
            vectorstore = self._get_vectorstore()
            text = summary.text_for_embedding

            # 元数据
            metadata = {
                "turn_id": summary.turn_id,
                "turn_number": str(summary.turn_number),
                "query_gist": summary.query_gist[:200],
                "topic_tags": ", ".join(summary.topic_tags),
                "importance_score": str(summary.importance_score),
            }

            # 存储到 ChromaDB
            vectorstore.add_texts(
                texts=[text],
                metadatas=[metadata],
                ids=[summary.turn_id],
            )

            # 本地缓存
            self._summaries[summary.turn_id] = summary

            return True
        except Exception as e:
            import logging
            logging.getLogger("iris.retriever").warning(
                f"索引 Turn {summary.turn_id} 失败: {e}"
            )
            return False

    def index_batch(self, summaries: List[TurnSummary]) -> int:
        """批量索引 TurnSummary。返回成功索引的数量。"""
        count = 0
        for summary in summaries:
            if self.index(summary):
                count += 1
        return count

    # ─── 检索 ───

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        min_relevance: float = 0.0,
    ) -> RetrievalResult:
        """
        检索与 query 语义相关的历史 Turn。

        Args:
            query: 当前用户问题
            top_k: 返回的最相关结果数
            min_relevance: 最低相关度阈值（0-1）

        Returns:
            RetrievalResult（含检索到的 Turn 和拼接好的 context_text）
        """
        try:
            vectorstore = self._get_vectorstore()

            # 相似度搜索（返回文档 + 分数）
            docs_with_scores = vectorstore.similarity_search_with_relevance_scores(
                query, k=top_k
            )
        except Exception:
            # ChromaDB 为空或出错
            return RetrievalResult(query=query)

        retrieved = []
        for doc, score in docs_with_scores:
            if score < min_relevance:
                continue

            turn_id = doc.metadata.get("turn_id", "")
            summary = self._summaries.get(turn_id)

            if summary:
                retrieved.append(RetrievedTurn(
                    turn_id=summary.turn_id,
                    turn_number=summary.turn_number,
                    query_gist=summary.query_gist,
                    key_facts=summary.key_facts,
                    conclusions=summary.conclusions,
                    topic_tags=summary.topic_tags,
                    importance_score=summary.importance_score,
                    relevance_score=round(score, 3),
                    summary_text=summary.text_for_embedding,
                ))
            else:
                # 从元数据构建简化版
                retrieved.append(RetrievedTurn(
                    turn_id=turn_id,
                    turn_number=int(doc.metadata.get("turn_number", 0)),
                    query_gist=doc.metadata.get("query_gist", ""),
                    key_facts=[],
                    conclusions=[],
                    topic_tags=doc.metadata.get("topic_tags", "").split(", "),
                    importance_score=float(doc.metadata.get("importance_score", 0.5)),
                    relevance_score=round(score, 3),
                    summary_text=doc.page_content,
                ))

        # 按重要度 + 相关度综合排序
        retrieved.sort(
            key=lambda r: r.relevance_score * 0.7 + r.importance_score * 0.3,
            reverse=True,
        )

        # 构建 context_text
        context_parts = []
        total_tokens = 0
        for r in retrieved:
            text = r.display_text
            tokens = count_tokens(text)
            if total_tokens + tokens > 3000:  # 最多 3000 tokens
                break
            context_parts.append(text)
            total_tokens += tokens

        context_text = (
            "## 相关历史研究（跨轮语义检索）\n\n" +
            "\n\n".join(context_parts)
            if context_parts else ""
        )

        return RetrievalResult(
            query=query,
            retrieved_turns=retrieved,
            context_text=context_text,
            total_tokens=total_tokens,
        )

    # ─── 维护 ───

    def count_indexed(self) -> int:
        """返回已索引的 Turn 数量。"""
        try:
            vectorstore = self._get_vectorstore()
            return vectorstore._collection.count()
        except Exception:
            return len(self._summaries)

    def delete_turn(self, turn_id: str) -> bool:
        """从索引中删除指定 Turn。"""
        try:
            vectorstore = self._get_vectorstore()
            vectorstore.delete(ids=[turn_id])
            self._summaries.pop(turn_id, None)
            return True
        except Exception:
            return False

    def clear_all(self) -> bool:
        """清空所有索引（慎用）。"""
        try:
            vectorstore = self._get_vectorstore()
            vectorstore.delete_collection()
            self._vectorstore = None
            self._summaries.clear()
            return True
        except Exception:
            return False

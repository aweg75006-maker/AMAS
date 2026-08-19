"""
BM25 关键词稀疏检索（自 hybrid-rag-graph-master 移植）

为什么需要它：
    稠密向量检索擅长「语义相似」，但对「专有名词 / 术语 / 条款编号 / 代码片段」
    这类字面匹配不敏感——一句话换个说法向量能召回，但搜「第8条」「扣款50元」
    这种精确关键词时，向量反而容易漏。BM25 基于词频统计，正好补这块召回盲区。

双方实现的差异：
    - 只保留核心能力：jieba 中文分词 + rank_bm25 的 BM25Okapi 建索引与检索；
    - 删掉了对方项目里「员工手册专用关键词白名单 / pickle 持久化 / 过滤检索」等
      与本项目无关的片段，避免引入无谓复杂度；
    - 检索结果直接返回 langchain 的 `Document`，与本项目稠密召回的格式完全一致，
      因此能无缝并入现有的「融合 → CrossEncoder 重排 → 评估」流水线，
      不需要复制对方那套加权融合逻辑（重排已经承担融合职责）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import jieba
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi


# 最小安全停用词：只过滤绝对无信息量的助词 / 语气词，避免误删关键词。
# （相比原项目大幅简化——去掉了领域专用的关键词白名单与复杂的保留规则，
#   仅保留最通用的中文停用词，适配本项目通用研究场景。）
_STOPWORDS = {
    # 结构 / 时态 / 语气助词（绝对安全）
    "的", "地", "得", "了", "着", "过",
    "啊", "呀", "呢", "吗", "吧", "啦", "哇", "哦", "哟",
    # 常见语气副词（相对安全）
    "就", "都", "也", "还", "又", "再", "却", "倒",
}


@dataclass
class BM25Doc:
    """BM25 内部文档结构：原文、分词结果、元数据。"""

    id: str
    text: str
    tokens: List[str]
    metadata: Dict[str, Any]


class BM25Retriever:
    """BM25 关键词检索器（轻量移植版）。"""

    def __init__(
        self,
        use_jieba: bool = True,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        """
        初始化 BM25 检索器。

        Args:
            use_jieba: 是否用 jieba 做中文分词（中文场景务必开启）。
            k1: BM25 参数，控制词频饱和度（越大对高频词惩罚越弱）。
            b:  BM25 参数，控制文档长度归一化（0=不归一，1=完全归一）。
        """
        self.use_jieba = use_jieba
        self.k1 = k1
        self.b = b

        # BM25 模型与文档索引（建索引前为 None）
        self.bm25: Optional[BM25Okapi] = None
        self.docs: List[BM25Doc] = []
        self._id_to_idx: Dict[str, int] = {}

        # 预热 jieba 词典，避免首次分词时的初始化抖动
        if use_jieba:
            jieba.initialize()

    def build_index(self, documents: List[Dict[str, Any]]) -> None:
        """
        用 {id, text, metadata} 列表构建 BM25 倒排索引。

        Args:
            documents: 每个元素含 id（可缺省）、text（必填）、metadata（可缺省）。
        """
        self.docs = []
        self._id_to_idx = {}
        tokenized: List[List[str]] = []

        for i, doc in enumerate(documents):
            doc_id = str(doc.get("id", i))
            text = doc.get("text", "")
            tokens = self._tokenize(text)
            self.docs.append(
                BM25Doc(
                    id=doc_id,
                    text=text,
                    tokens=tokens,
                    metadata=doc.get("metadata", {}) or {},
                )
            )
            self._id_to_idx[doc_id] = i
            tokenized.append(tokens)

        # 空语料时 bm25 保持 None，search 直接返回空列表
        if tokenized:
            self.bm25 = BM25Okapi(tokenized, k1=self.k1, b=self.b)

    def search(
        self,
        query: str,
        top_k: int = 10,
        score_threshold: float = 0.0,
    ) -> List[Document]:
        """
        对 query 做 BM25 关键词检索。

        Returns:
            与稠密召回同格式的 langchain `Document` 列表，metadata 里附带
            `retrieval_type="bm25"` 与原始 `bm25_score`，便于下游区分与调试。
        """
        if self.bm25 is None or not self.docs:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = self.bm25.get_scores(query_tokens)
        # 取分数最高的 top_k 个下标
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        max_score = max(scores) if len(scores) else 0.0

        results: List[Document] = []
        for idx in top_indices:
            score = float(scores[idx])
            # 过滤阈值只在「存在正分」时生效：BM25 的 ATIRE 变体在词频 df≈N/2 时
            # idf 会退化为 0，小语料 / 超高频词场景下所有文档可能都是 0 分——
            # 此时若还用绝对阈值会全部滤掉导致召回为空。本通道定位是「召回补充」，
            # 精度由下游 CrossEncoder 重排把关，所以退化场景下保留 top-k 更稳妥。
            if max_score > 0 and score <= score_threshold:
                continue
            doc = self.docs[idx]
            results.append(
                Document(
                    page_content=doc.text,
                    metadata={
                        **(doc.metadata or {}),
                        "id": doc.id,
                        "retrieval_type": "bm25",
                        "bm25_score": score,
                    },
                )
            )
        return results

    def _tokenize(self, text: str) -> List[str]:
        """文本分词：中文走 jieba，其余按空格切；过滤空串与停用词。"""
        if not text:
            return []

        if self.use_jieba:
            # 用 cut_for_search（搜索式分词）而非普通 cut：它会把一个词做多粒度切分
            # （如「警告处分」→「警告」「处分」），避免「查询分词」与「文档分词」粒度不一致
            # 导致本该命中的文档因 token 对不上而被 BM25 过滤掉（这是中文 BM25 常见漏召回根因）。
            tokens = list(jieba.cut_for_search(text))
        else:
            tokens = text.split()

        return [
            tok
            for tok in tokens
            if tok and tok.strip() and tok not in _STOPWORDS
        ]

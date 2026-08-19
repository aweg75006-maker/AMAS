import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Optional
from langchain_community.document_loaders import PyPDFLoader
from langchain_core import vectorstores
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("iris.rag")

try:
    from sentence_transformers import CrossEncoder
except ImportError:
    CrossEncoder = None

RERANKER_MODEL_NAME = settings.rag_reranker_model # Cross-Encoder 重排序模型
_reranker = None

def get_reranker():
    global _reranker
    if _reranker is not None:
        return _reranker
    if CrossEncoder is None:
        raise RuntimeError(
            "未安装 sentence-transformers，无法启用 reranking。请执行：pip install sentence-transformers"
        )
    # 优先从项目内固定本地路径加载重排序模型，避免每次运行都触发 HuggingFace 下载/校验。
    local_path = str(settings.rag_reranker_local_path)
    if os.path.isdir(local_path) and os.path.exists(os.path.join(local_path, "config.json")):
        # 权重已固定到本地，强制离线加载，彻底屏蔽 HuggingFace 网络请求。
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        _reranker = CrossEncoder(local_path)
    else:
        # 本地权重缺失时回退到按 HuggingFace repo id 加载（首次会下载并缓存）。
        _reranker = CrossEncoder(RERANKER_MODEL_NAME)
    return _reranker

class RerankRetriever(BaseRetriever):
    """
    两阶段检索：
    1) Chroma 向量召回 fetch_k 个候选
    2) Cross-Encoder rerank
    3) 返回 top_k
    """

    vectorstore: Any
    reranker: Any
    top_k: int = 5
    fetch_k: int = 20

    def _get_relevant_documents(self, query: str) -> list[Document]:
        # 1) 先召回更多候选
        candidates: list[Document] = self.vectorstore.similarity_search(query, k=self.fetch_k)
        return rerank_documents(query, candidates, self.reranker, top_k=self.top_k)


def rerank_documents(
    query: str,
    candidates: list[Document],
    reranker: Any | None = None,
    *,
    top_k: int | None = None,
) -> list[Document]:
    """Rank document candidates with the shared Cross-Encoder model."""
    if not candidates:
        return []
    model = reranker or get_reranker()
    pairs = [(query, document.page_content) for document in candidates]
    scores = model.predict(pairs)
    ranked = sorted(zip(candidates, scores), key=lambda item: float(item[1]), reverse=True)
    limit = len(ranked) if top_k is None else max(0, top_k)
    return [document for document, _ in ranked[:limit]]

# 定义数据存储路径
DB_PATH = str(settings.rag_chroma_db_path)   # 数据库文件存这里
UPLOAD_DIR = str(settings.rag_upload_dir) # 用户上传的 PDF 存这里
DEFAULT_KNOWLEDGE_BASE_ID = "kb_default"


def _safe_knowledge_base_id(knowledge_base_id: str | None = None) -> str:
    raw = (knowledge_base_id or DEFAULT_KNOWLEDGE_BASE_ID).strip()
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in raw)
    return safe or DEFAULT_KNOWLEDGE_BASE_ID


def get_db_path(knowledge_base_id: str | None = None) -> str:
    return str(Path(DB_PATH) / _safe_knowledge_base_id(knowledge_base_id))


def get_upload_dir(knowledge_base_id: str | None = None) -> str:
    return str(Path(UPLOAD_DIR) / _safe_knowledge_base_id(knowledge_base_id))


@lru_cache
def get_embeddings():
    # embeddings = HuggingFaceEmbeddings(model_name="moka-ai/m3e-base")
    # 这里用的是阿里云的词嵌入模型，需要配置环境变量，不行的话可以用上面的
    return DashScopeEmbeddings(
        model=settings.rag_embedding_model,
        dashscope_api_key=settings.require_dashscope_api_key(),
    )

def reset_knowledge_base(knowledge_base_id: str | None = None):
    """
    重置知识库：
    Windows 兼容版修复：不删除 DB 文件夹（避免 WinError 32），而是清空数据。
    """

    upload_dir = get_upload_dir(knowledge_base_id)
    db_path = get_db_path(knowledge_base_id)

    if os.path.exists(upload_dir):
        try:
            shutil.rmtree(upload_dir)
        except Exception as e:
            logger.warning("rag_upload_dir_cleanup_failed", exc_info=True)
    os.makedirs(upload_dir, exist_ok=True)


    logger.info("rag_reset_started")
    try:
        if os.path.exists(db_path):
            vectorstore = Chroma(
                persist_directory=db_path,
                embedding_function=get_embeddings(),
            )
            try:
                vectorstore.delete_collection()
                logger.info("rag_collection_deleted")
            except Exception:
                pass
    except Exception as e:
        logger.warning("rag_reset_nonfatal_error", exc_info=True)

def process_documents(file_paths: List[str], knowledge_base_id: str | None = None):
    """
    核心逻辑：读取 -> 切片 -> 向量化 -> 存储
    可以考虑 VIT
    """
    all_splits = []
    
    for file_path in file_paths:
        logger.info("rag_document_processing_started", extra={"filename": os.path.basename(file_path)})
        try:
            loader = PyPDFLoader(file_path) # 只提取文本层
            docs = loader.load()
            
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=settings.rag_chunk_size,
                chunk_overlap=settings.rag_chunk_overlap
            )
            splits = text_splitter.split_documents(docs)
            all_splits.extend(splits)
        except Exception as e:
            logger.exception(
                "rag_document_processing_failed",
                extra={"filename": os.path.basename(file_path)},
            )
    
    if all_splits:
        db_path = get_db_path(knowledge_base_id)
        logger.info("rag_vector_write_started", extra={"split_count": len(all_splits)})
        Chroma.from_documents(
            documents=all_splits,
            embedding=get_embeddings(),
            persist_directory=db_path
        )
        logger.info("rag_vector_write_completed", extra={"split_count": len(all_splits)})
    
    return len(all_splits)

def get_retriever(knowledge_base_id: str | None = None):
    """
    获取检索器：给 Agent 用的接口
    """
    db_path = get_db_path(knowledge_base_id)
    if not os.path.exists(db_path) or not os.listdir(db_path):
        return None
    vectorstore = Chroma(
        persist_directory=db_path,
        embedding_function=get_embeddings(),
    )
    top_k = settings.rag_top_k
    fetch_k = settings.rag_fetch_k
    reranker = get_reranker()
    return RerankRetriever(vectorstore=vectorstore, reranker=reranker, top_k=top_k, fetch_k=fetch_k)


# BM25 稀疏召回索引缓存：knowledge_base_id -> (集合文档数, BM25Retriever)。
# 按「文档数是否变化」决定是否重建索引，避免每次检索都重新分词建索引
# （与 hybrid-rag-graph-master 的缓存思路一致，这里用文档数做失效判断，更简单）。
_bm25_cache: dict[str, tuple[int, Any]] = {}


def get_bm25_candidates(
    query: str,
    knowledge_base_id: str | None = None,
    top_k: int | None = None,
) -> list[Document]:
    """
    基于本地知识库全量语料构建 BM25 索引并做关键词检索。

    作为稠密向量召回的补充通道：向量检索漏掉但字面命中的片段，会在这里被找回，
    并入候选池后统一交给 CrossEncoder 重排。返回与稠密召回同格式的 `Document` 列表。

    降级策略：任何环节（依赖缺失 / 集合为空 / 建索引失败）都返回空列表，
    绝不阻断主流程——BM25 是「增益」而非「必需」。
    """
    db_path = get_db_path(knowledge_base_id)
    if not os.path.exists(db_path) or not os.listdir(db_path):
        return []

    try:
        from app.rag.bm25 import BM25Retriever
    except Exception:
        # 未安装 jieba / rank_bm25 时静默跳过，不影响稠密检索
        return []

    try:
        vectorstore = Chroma(
            persist_directory=db_path,
            embedding_function=get_embeddings(),
        )
        # 取集合文档总数，用于判断缓存是否过期。
        # 注意：langchain_community 的 Chroma 包装类没有 count()，需访问底层 chromadb collection。
        try:
            count = int(vectorstore._collection.count())
        except Exception:
            return []
        if count == 0:
            return []

        cache_key = _safe_knowledge_base_id(knowledge_base_id)
        cached = _bm25_cache.get(cache_key)
        # 缓存未命中或集合文档数变化 → 重建索引
        if cached is None or cached[0] != count:
            data = vectorstore.get(include=["documents", "metadatas"], limit=10000)
            raw_docs = data.get("documents") or []
            raw_meta = data.get("metadatas") or []
            ids = data.get("ids") or []
            documents = []
            for i, text in enumerate(raw_docs):
                if not text:
                    continue
                documents.append(
                    {
                        "id": str(ids[i]) if i < len(ids) else str(i),
                        "text": text,
                        "metadata": (raw_meta[i] if i < len(raw_meta) else {}) or {},
                    }
                )
            if not documents:
                return []
            retriever = BM25Retriever(use_jieba=True)
            retriever.build_index(documents)
            _bm25_cache[cache_key] = (count, retriever)
            cached = _bm25_cache[cache_key]

        return cached[1].search(query, top_k=top_k or settings.rag_fetch_k)
    except Exception:
        logger.warning("bm25_candidates_unavailable", exc_info=True)
        return []


def get_candidate_documents(
    query: str,
    knowledge_base_id: str | None = None,
) -> list[Document]:
    """Return wide local recall candidates for cross-source reranking."""
    db_path = get_db_path(knowledge_base_id)
    if not os.path.exists(db_path) or not os.listdir(db_path):
        return []
    vectorstore = Chroma(
        persist_directory=db_path,
        embedding_function=get_embeddings(),
    )
    candidates = vectorstore.similarity_search(query, k=settings.rag_fetch_k)

    # BM25 稀疏召回作为补充通道：扩大候选池，后续由 CrossEncoder 统一重排。
    # 同源（同一切片）的稠密 / BM25 结果会在 researcher 的 fuse_candidates 按
    # SHA256 去重，因此这里直接拼接即可，不会引入重复。
    if getattr(settings, "rag_bm25_enabled", True):
        try:
            bm25_docs = get_bm25_candidates(
                query, knowledge_base_id, top_k=settings.rag_fetch_k
            )
            if bm25_docs:
                candidates = candidates + bm25_docs
        except Exception:
            logger.warning("bm25_recall_skipped", exc_info=True)

    return candidates

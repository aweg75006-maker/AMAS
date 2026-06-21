import os
import shutil
from functools import lru_cache
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
        if not candidates:
            return []

        # 2) rerank：对 (query, doc_text) 打分
        pairs = [(query, d.page_content) for d in candidates]
        scores = self.reranker.predict(pairs)

        # 3) 按分数排序，取 top_k
        ranked = sorted(zip(candidates, scores), key=lambda x: float(x[1]), reverse=True)
        top_docs = [doc for doc, _ in ranked[: self.top_k]]

        return top_docs

# 定义数据存储路径
DB_PATH = str(settings.rag_chroma_db_path)   # 数据库文件存这里
UPLOAD_DIR = str(settings.rag_upload_dir) # 用户上传的 PDF 存这里


@lru_cache
def get_embeddings():
    # embeddings = HuggingFaceEmbeddings(model_name="moka-ai/m3e-base")
    # 这里用的是阿里云的词嵌入模型，需要配置环境变量，不行的话可以用上面的
    return DashScopeEmbeddings(
        model=settings.rag_embedding_model,
        dashscope_api_key=settings.require_dashscope_api_key(),
    )

def reset_knowledge_base():
    """
    重置知识库：
    Windows 兼容版修复：不删除 DB 文件夹（避免 WinError 32），而是清空数据。
    """

    if os.path.exists(UPLOAD_DIR):
        try:
            shutil.rmtree(UPLOAD_DIR)
        except Exception as e:
            logger.warning("rag_upload_dir_cleanup_failed", exc_info=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)


    logger.info("rag_reset_started")
    try:
        if os.path.exists(DB_PATH):
            vectorstore = Chroma(
                persist_directory=DB_PATH,
                embedding_function=get_embeddings(),
            )
            try:
                vectorstore.delete_collection()
                logger.info("rag_collection_deleted")
            except Exception:
                pass
    except Exception as e:
        logger.warning("rag_reset_nonfatal_error", exc_info=True)

def process_documents(file_paths: List[str]):
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
        logger.info("rag_vector_write_started", extra={"split_count": len(all_splits)})
        Chroma.from_documents(
            documents=all_splits,
            embedding=get_embeddings(),
            persist_directory=DB_PATH
        )
        logger.info("rag_vector_write_completed", extra={"split_count": len(all_splits)})
    
    return len(all_splits)

def get_retriever():
    """
    获取检索器：给 Agent 用的接口
    """
    if not os.path.exists(DB_PATH) or not os.listdir(DB_PATH):
        return None
    vectorstore = Chroma(
        persist_directory=DB_PATH,
        embedding_function=get_embeddings(),
    )
    top_k = settings.rag_top_k
    fetch_k = settings.rag_fetch_k
    reranker = get_reranker()
    return RerankRetriever(vectorstore=vectorstore, reranker=reranker, top_k=top_k, fetch_k=fetch_k)

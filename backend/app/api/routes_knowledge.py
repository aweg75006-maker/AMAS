from typing import List

from fastapi import APIRouter, File, UploadFile

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.rag.engine import UPLOAD_DIR, process_documents, reset_knowledge_base
from app.services.upload_security import save_upload_batch, validate_upload_files


router = APIRouter()
logger = get_logger("iris.api.knowledge")


@router.post("/clear")
async def clear_endpoint():
    try:
        reset_knowledge_base()
        return {"message": "知识库已重置", "status": "success"}
    except Exception as e:
        logger.exception("knowledge_clear_failed")
        raise AppError(
            code="KNOWLEDGE_CLEAR_FAILED",
            message="清空知识库失败",
            status_code=500,
            details={"reason": str(e)},
        )


@router.post("/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """Upload documents into the current knowledge base."""
    try:
        validate_upload_files(files)
        reset_knowledge_base()

        saved_paths = save_upload_batch(files, UPLOAD_DIR)
        chunks_num = process_documents(saved_paths)

        return {
            "status": "success",
            "file_count": len(files),
            "chunks_stored": chunks_num,
            "message": "文档解析完成，知识库构建成功",
        }
    except AppError:
        raise
    except Exception as e:
        logger.exception("document_upload_failed")
        raise AppError(
            code="DOCUMENT_UPLOAD_FAILED",
            message="上传处理失败",
            status_code=500,
            details={"reason": str(e)},
        )

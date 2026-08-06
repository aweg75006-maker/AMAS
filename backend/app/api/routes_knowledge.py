import os
from typing import List

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.api.rate_limits import upload_rate_limit
from app.api.schemas import CreateKnowledgeBaseRequest
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.rag.engine import get_upload_dir, process_documents, reset_knowledge_base
from app.services.knowledge_base_service import get_knowledge_base_service
from app.services.upload_security import save_upload_batch, validate_upload_files


router = APIRouter()
logger = get_logger("iris.api.knowledge")


@router.get("/knowledge-bases")
async def list_knowledge_bases():
    service = await get_knowledge_base_service()
    bases = await service.list_knowledge_bases()
    return {"items": [kb.to_dict() for kb in bases]}


@router.post("/knowledge-bases")
async def create_knowledge_base(
    request: CreateKnowledgeBaseRequest,
):
    if not request.name.strip():
        raise AppError(
            code="INVALID_KNOWLEDGE_BASE_NAME",
            message="知识库名称不能为空",
            status_code=400,
        )

    service = await get_knowledge_base_service()
    kb = await service.create_knowledge_base(
        name=request.name.strip(),
        description=request.description,
        visibility=request.visibility,
    )
    return kb.to_dict()


@router.get("/knowledge-bases/{knowledge_base_id}/documents")
async def list_knowledge_base_documents(
    knowledge_base_id: str,
):
    service = await get_knowledge_base_service()
    kb = await service.get_knowledge_base(knowledge_base_id)
    if kb is None:
        raise AppError(
            code="KNOWLEDGE_BASE_NOT_FOUND",
            message="知识库不存在",
            status_code=404,
            details={"knowledge_base_id": knowledge_base_id},
        )

    documents = await service.list_documents(knowledge_base_id)
    return {"items": [document.to_dict() for document in documents]}


@router.post("/clear")
async def clear_endpoint(
    knowledge_base_id: str | None = Query(default=None),
):
    try:
        service = await get_knowledge_base_service()
        if knowledge_base_id:
            kb = await service.get_knowledge_base(knowledge_base_id)
            if kb is None:
                raise AppError(
                    code="KNOWLEDGE_BASE_NOT_FOUND",
                    message="知识库不存在",
                    status_code=404,
                    details={"knowledge_base_id": knowledge_base_id},
                )
        else:
            kb = await service.ensure_default_knowledge_base()
        await service.clear_documents(kb.knowledge_base_id)
        reset_knowledge_base(kb.knowledge_base_id)
        return {
            "message": "知识库已重置",
            "status": "success",
            "knowledge_base_id": kb.knowledge_base_id,
        }
    except AppError:
        raise
    except Exception as e:
        logger.exception("knowledge_clear_failed")
        raise AppError(
            code="KNOWLEDGE_CLEAR_FAILED",
            message="清空知识库失败",
            status_code=500,
            details={"reason": str(e)},
        )


@router.post("/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    knowledge_base_id: str | None = Form(default=None),
    _rate_limit: None = Depends(upload_rate_limit),
):
    """Upload documents into the current knowledge base."""
    try:
        validate_upload_files(files)
        service = await get_knowledge_base_service()
        if knowledge_base_id:
            kb = await service.get_knowledge_base(knowledge_base_id)
            if kb is None:
                raise AppError(
                    code="KNOWLEDGE_BASE_NOT_FOUND",
                    message="知识库不存在",
                    status_code=404,
                    details={"knowledge_base_id": knowledge_base_id},
                )
        else:
            kb = await service.ensure_default_knowledge_base()
        await service.clear_documents(kb.knowledge_base_id)
        reset_knowledge_base(kb.knowledge_base_id)

        saved_paths = save_upload_batch(files, get_upload_dir(kb.knowledge_base_id))
        chunks_num = process_documents(saved_paths, knowledge_base_id=kb.knowledge_base_id)
        chunk_count_per_file = chunks_num // len(saved_paths) if saved_paths else 0

        documents = []
        for file, saved_path in zip(files, saved_paths):
            stat = os.stat(saved_path)
            document = await service.record_document(
                knowledge_base_id=kb.knowledge_base_id,
                filename=os.path.basename(saved_path),
                original_filename=file.filename or "",
                content_type=file.content_type or "",
                size_bytes=stat.st_size,
                storage_path=saved_path,
                chunk_count=chunk_count_per_file,
            )
            documents.append(document.to_dict())

        return {
            "status": "success",
            "knowledge_base_id": kb.knowledge_base_id,
            "file_count": len(files),
            "chunks_stored": chunks_num,
            "documents": documents,
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

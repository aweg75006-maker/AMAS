import time
from uuid import uuid4

from app.core.config import settings
from app.models.domain import (
    DocumentRecord,
    DocumentStatus,
    KnowledgeBase,
    KnowledgeBaseVisibility,
)
from app.repositories.knowledge_base_repository import (
    KnowledgeBaseRepository,
    get_knowledge_base_repository,
)


DEFAULT_KNOWLEDGE_BASE_ID = "kb_default"
DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"


class KnowledgeBaseService:
    """Metadata service for knowledge bases and documents.

    The service owns defaults and lifecycle rules for the local RAG demo.
    """

    def __init__(self, repository: KnowledgeBaseRepository):
        self.repository = repository

    def default_knowledge_base_id(self) -> str:
        return DEFAULT_KNOWLEDGE_BASE_ID

    async def ensure_default_knowledge_base(
        self,
    ) -> KnowledgeBase:
        knowledge_base_id = self.default_knowledge_base_id()
        existing = await self.get_knowledge_base(knowledge_base_id)
        if existing:
            return existing

        kb = KnowledgeBase(
            knowledge_base_id=knowledge_base_id,
            name=DEFAULT_KNOWLEDGE_BASE_NAME,
            description="兼容当前单知识库上传流程的默认知识库",
            visibility=KnowledgeBaseVisibility.PRIVATE.value,
            embedding_model=settings.rag_embedding_model,
        )
        await self.save_knowledge_base(kb)
        return kb

    async def create_knowledge_base(
        self,
        name: str,
        description: str = "",
        visibility: str = KnowledgeBaseVisibility.PRIVATE.value,
    ) -> KnowledgeBase:
        now = time.time()
        kb = KnowledgeBase(
            knowledge_base_id=f"kb_{uuid4().hex[:12]}",
            name=name,
            description=description,
            visibility=visibility,
            embedding_model=settings.rag_embedding_model,
            created_at=now,
            updated_at=now,
        )
        await self.save_knowledge_base(kb)
        return kb

    async def save_knowledge_base(self, kb: KnowledgeBase) -> None:
        await self.repository.save_knowledge_base(kb)

    async def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase | None:
        return await self.repository.get_knowledge_base(knowledge_base_id)

    async def list_knowledge_bases(self) -> list[KnowledgeBase]:
        await self.ensure_default_knowledge_base()
        return await self.repository.list_knowledge_bases()

    async def record_document(
        self,
        *,
        knowledge_base_id: str,
        filename: str,
        original_filename: str = "",
        content_type: str = "",
        size_bytes: int = 0,
        storage_path: str = "",
        chunk_count: int = 0,
        status: str = DocumentStatus.INDEXED.value,
    ) -> DocumentRecord:
        now = time.time()
        record = DocumentRecord(
            document_id=f"doc_{uuid4().hex[:12]}",
            knowledge_base_id=knowledge_base_id,
            filename=filename,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
            status=status,
            chunk_count=chunk_count,
            created_at=now,
            updated_at=now,
        )
        await self.save_document(record)
        return record

    async def save_document(self, document: DocumentRecord) -> None:
        await self.repository.save_document(document)

    async def list_documents(self, knowledge_base_id: str) -> list[DocumentRecord]:
        return await self.repository.list_documents(knowledge_base_id)

    async def clear_documents(self, knowledge_base_id: str) -> None:
        await self.repository.clear_documents(knowledge_base_id)


async def get_knowledge_base_service() -> KnowledgeBaseService:
    repository = await get_knowledge_base_repository()
    return KnowledgeBaseService(repository)

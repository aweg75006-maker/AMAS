import time
from uuid import uuid4

from app.core.config import settings
from app.core.identity import DEFAULT_TENANT_ID
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

    The service owns business defaults and lifecycle rules. Physical
    persistence is delegated to a repository, so local Redis metadata and
    enterprise PostgreSQL metadata share the same API surface.
    """

    def __init__(self, repository: KnowledgeBaseRepository):
        self.repository = repository

    def default_knowledge_base_id(self, tenant_id: str = DEFAULT_TENANT_ID) -> str:
        if tenant_id == DEFAULT_TENANT_ID:
            return DEFAULT_KNOWLEDGE_BASE_ID
        return f"kb_default_{tenant_id}"

    async def ensure_default_knowledge_base(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
        created_by: str = "",
    ) -> KnowledgeBase:
        knowledge_base_id = self.default_knowledge_base_id(tenant_id)
        existing = await self.get_knowledge_base_for_tenant(
            knowledge_base_id,
            tenant_id,
        )
        if existing:
            return existing

        kb = KnowledgeBase(
            knowledge_base_id=knowledge_base_id,
            tenant_id=tenant_id,
            name=DEFAULT_KNOWLEDGE_BASE_NAME,
            description="兼容当前单知识库上传流程的默认知识库",
            visibility=KnowledgeBaseVisibility.PRIVATE.value,
            embedding_model=settings.rag_embedding_model,
            created_by=created_by,
        )
        await self.save_knowledge_base(kb)
        return kb

    async def create_knowledge_base(
        self,
        name: str,
        description: str = "",
        tenant_id: str = DEFAULT_TENANT_ID,
        visibility: str = KnowledgeBaseVisibility.PRIVATE.value,
        created_by: str = "",
    ) -> KnowledgeBase:
        now = time.time()
        kb = KnowledgeBase(
            knowledge_base_id=f"kb_{uuid4().hex[:12]}",
            tenant_id=tenant_id,
            name=name,
            description=description,
            visibility=visibility,
            embedding_model=settings.rag_embedding_model,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        await self.save_knowledge_base(kb)
        return kb

    async def save_knowledge_base(self, kb: KnowledgeBase) -> None:
        await self.repository.save_knowledge_base(kb)

    async def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase | None:
        return await self.repository.get_knowledge_base(knowledge_base_id)

    async def get_knowledge_base_for_tenant(
        self,
        knowledge_base_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> KnowledgeBase | None:
        kb = await self.get_knowledge_base(knowledge_base_id)
        if kb is None or kb.tenant_id != tenant_id:
            return None
        return kb

    async def list_knowledge_bases(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[KnowledgeBase]:
        await self.ensure_default_knowledge_base(tenant_id=tenant_id)
        return await self.repository.list_knowledge_bases(tenant_id)

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
        tenant_id: str = DEFAULT_TENANT_ID,
        created_by: str = "",
        status: str = DocumentStatus.INDEXED.value,
    ) -> DocumentRecord:
        now = time.time()
        record = DocumentRecord(
            document_id=f"doc_{uuid4().hex[:12]}",
            knowledge_base_id=knowledge_base_id,
            tenant_id=tenant_id,
            filename=filename,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
            status=status,
            chunk_count=chunk_count,
            created_by=created_by,
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

import pytest

from app.services.knowledge_base_service import (
    DEFAULT_KNOWLEDGE_BASE_ID,
    KnowledgeBaseService,
)
from app.repositories.knowledge_base_repository import RedisKnowledgeBaseRepository
from app.utils.redis_client import RedisClient


@pytest.mark.asyncio
async def test_default_knowledge_base_is_idempotent():
    redis = RedisClient(url="redis://localhost:1/0")
    await redis.connect()
    try:
        service = KnowledgeBaseService(RedisKnowledgeBaseRepository(redis))

        first = await service.ensure_default_knowledge_base()
        second = await service.ensure_default_knowledge_base()

        assert first.knowledge_base_id == DEFAULT_KNOWLEDGE_BASE_ID
        assert second.knowledge_base_id == DEFAULT_KNOWLEDGE_BASE_ID
        assert first.to_dict() == second.to_dict()
    finally:
        await redis.close()


@pytest.mark.asyncio
async def test_create_and_list_knowledge_bases():
    redis = RedisClient(url="redis://localhost:1/0")
    await redis.connect()
    try:
        service = KnowledgeBaseService(RedisKnowledgeBaseRepository(redis))

        created = await service.create_knowledge_base(
            name="研发资料",
        )
        bases = await service.list_knowledge_bases()

        assert any(kb.knowledge_base_id == created.knowledge_base_id for kb in bases)
        assert any(kb.knowledge_base_id == DEFAULT_KNOWLEDGE_BASE_ID for kb in bases)
    finally:
        await redis.close()


@pytest.mark.asyncio
async def test_record_list_and_clear_documents():
    redis = RedisClient(url="redis://localhost:1/0")
    await redis.connect()
    try:
        service = KnowledgeBaseService(RedisKnowledgeBaseRepository(redis))
        kb = await service.ensure_default_knowledge_base()

        document = await service.record_document(
            knowledge_base_id=kb.knowledge_base_id,
            filename="stored.pdf",
            original_filename="report.pdf",
            content_type="application/pdf",
            size_bytes=123,
            storage_path="/tmp/stored.pdf",
            chunk_count=4,
        )

        documents = await service.list_documents(kb.knowledge_base_id)
        assert [doc.document_id for doc in documents] == [document.document_id]
        assert documents[0].chunk_count == 4

        await service.clear_documents(kb.knowledge_base_id)
        assert await service.list_documents(kb.knowledge_base_id) == []
    finally:
        await redis.close()

from __future__ import annotations

from typing import Protocol

from app.models.domain import DocumentRecord, KnowledgeBase
from app.utils.redis_client import RedisClient, get_redis


class KnowledgeBaseRepository(Protocol):
    backend_name: str

    async def ping(self) -> bool: ...
    async def save_knowledge_base(self, kb: KnowledgeBase) -> None: ...
    async def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase | None: ...
    async def list_knowledge_bases(self) -> list[KnowledgeBase]: ...
    async def save_document(self, document: DocumentRecord) -> None: ...
    async def list_documents(self, knowledge_base_id: str) -> list[DocumentRecord]: ...
    async def clear_documents(self, knowledge_base_id: str) -> None: ...


class RedisKnowledgeBaseRepository:
    """Redis metadata storage used by the local RAG demo."""

    backend_name = "redis"

    def __init__(self, redis: RedisClient):
        self.redis = redis

    async def ping(self) -> bool:
        return await self.redis.ping()

    async def save_knowledge_base(self, kb: KnowledgeBase) -> None:
        await self.redis.hset(self._kb_key(kb.knowledge_base_id), kb.to_dict())

    async def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase | None:
        data = await self.redis.hgetall(self._kb_key(knowledge_base_id))
        return KnowledgeBase.from_dict(data) if data else None

    async def list_knowledge_bases(self) -> list[KnowledgeBase]:
        bases = []
        for key in await self.redis.keys("kb:*:meta"):
            data = await self.redis.hgetall(key)
            if data:
                kb = KnowledgeBase.from_dict(data)
                bases.append(kb)
        bases.sort(key=lambda item: item.updated_at, reverse=True)
        return bases

    async def save_document(self, document: DocumentRecord) -> None:
        await self.redis.hset(self._document_key(document.document_id), document.to_dict())
        await self.redis.rpush(self._kb_documents_key(document.knowledge_base_id), document.document_id)

    async def list_documents(self, knowledge_base_id: str) -> list[DocumentRecord]:
        documents = []
        for document_id in await self.redis.lrange(self._kb_documents_key(knowledge_base_id), 0, -1):
            data = await self.redis.hgetall(self._document_key(document_id))
            if data:
                documents.append(DocumentRecord.from_dict(data))
        documents.sort(key=lambda item: item.created_at, reverse=True)
        return documents

    async def clear_documents(self, knowledge_base_id: str) -> None:
        for document_id in await self.redis.lrange(self._kb_documents_key(knowledge_base_id), 0, -1):
            await self.redis.delete(self._document_key(document_id))
        await self.redis.delete(self._kb_documents_key(knowledge_base_id))

    @staticmethod
    def _kb_key(knowledge_base_id: str) -> str:
        return f"kb:{knowledge_base_id}:meta"

    @staticmethod
    def _kb_documents_key(knowledge_base_id: str) -> str:
        return f"kb:{knowledge_base_id}:documents"

    @staticmethod
    def _document_key(document_id: str) -> str:
        return f"document:{document_id}:meta"


async def get_knowledge_base_repository() -> KnowledgeBaseRepository:
    return RedisKnowledgeBaseRepository(await get_redis())

from __future__ import annotations

import asyncio
from typing import Protocol

from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.db.migrations import run_postgres_migrations
from app.models.domain import DocumentRecord, KnowledgeBase
from app.utils.redis_client import RedisClient, get_redis


class KnowledgeBaseRepository(Protocol):
    backend_name: str

    async def ping(self) -> bool:
        ...

    async def save_knowledge_base(self, kb: KnowledgeBase) -> None:
        ...

    async def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase | None:
        ...

    async def list_knowledge_bases(self, tenant_id: str) -> list[KnowledgeBase]:
        ...

    async def save_document(self, document: DocumentRecord) -> None:
        ...

    async def list_documents(self, knowledge_base_id: str) -> list[DocumentRecord]:
        ...

    async def clear_documents(self, knowledge_base_id: str) -> None:
        ...


class RedisKnowledgeBaseRepository:
    """Redis-backed metadata repository used by the current local runtime."""

    backend_name = "redis"

    def __init__(self, redis: RedisClient):
        self.redis = redis

    async def ping(self) -> bool:
        return await self.redis.ping()

    async def save_knowledge_base(self, kb: KnowledgeBase) -> None:
        await self.redis.hset(self._kb_key(kb.knowledge_base_id), kb.to_dict())

    async def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase | None:
        data = await self.redis.hgetall(self._kb_key(knowledge_base_id))
        if not data:
            return None
        return KnowledgeBase.from_dict(data)

    async def list_knowledge_bases(self, tenant_id: str) -> list[KnowledgeBase]:
        keys = await self.redis.keys("kb:*:meta")
        bases = []
        for key in keys:
            data = await self.redis.hgetall(key)
            if not data:
                continue
            kb = KnowledgeBase.from_dict(data)
            if kb.tenant_id == tenant_id:
                bases.append(kb)
        bases.sort(key=lambda item: item.updated_at, reverse=True)
        return bases

    async def save_document(self, document: DocumentRecord) -> None:
        await self.redis.hset(self._document_key(document.document_id), document.to_dict())
        await self.redis.rpush(
            self._kb_documents_key(document.knowledge_base_id),
            document.document_id,
        )

    async def list_documents(self, knowledge_base_id: str) -> list[DocumentRecord]:
        document_ids = await self.redis.lrange(
            self._kb_documents_key(knowledge_base_id),
            0,
            -1,
        )
        documents = []
        for document_id in document_ids:
            data = await self.redis.hgetall(self._document_key(document_id))
            if data:
                documents.append(DocumentRecord.from_dict(data))
        documents.sort(key=lambda item: item.created_at, reverse=True)
        return documents

    async def clear_documents(self, knowledge_base_id: str) -> None:
        document_ids = await self.redis.lrange(
            self._kb_documents_key(knowledge_base_id),
            0,
            -1,
        )
        for document_id in document_ids:
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


class PostgresKnowledgeBaseRepository:
    """PostgreSQL metadata repository for enterprise deployments."""

    backend_name = "postgres"

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        try:
            import asyncpg
        except ImportError as exc:
            raise ConfigurationError(
                "缺少 asyncpg，无法启用 PostgreSQL 元数据存储。请安装 backend/requirements.txt。"
            ) from exc

        self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        if settings.postgres_auto_migrate:
            await self.migrate()

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def migrate(self) -> None:
        await asyncio.to_thread(run_postgres_migrations, self.dsn)

    async def ping(self) -> bool:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            value = await conn.fetchval("SELECT 1")
        return value == 1

    async def save_knowledge_base(self, kb: KnowledgeBase) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge_bases (
                    knowledge_base_id, tenant_id, name, description, visibility,
                    embedding_model, chunking_strategy, created_by, created_at,
                    updated_at, status
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (knowledge_base_id) DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    visibility = EXCLUDED.visibility,
                    embedding_model = EXCLUDED.embedding_model,
                    chunking_strategy = EXCLUDED.chunking_strategy,
                    created_by = EXCLUDED.created_by,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at,
                    status = EXCLUDED.status
                """,
                kb.knowledge_base_id,
                kb.tenant_id,
                kb.name,
                kb.description,
                kb.visibility,
                kb.embedding_model,
                kb.chunking_strategy,
                kb.created_by,
                kb.created_at,
                kb.updated_at,
                kb.status,
            )

    async def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase | None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM knowledge_bases WHERE knowledge_base_id = $1",
                knowledge_base_id,
            )
        return KnowledgeBase.from_dict(dict(row)) if row else None

    async def list_knowledge_bases(self, tenant_id: str) -> list[KnowledgeBase]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM knowledge_bases
                WHERE tenant_id = $1
                ORDER BY updated_at DESC
                """,
                tenant_id,
            )
        return [KnowledgeBase.from_dict(dict(row)) for row in rows]

    async def save_document(self, document: DocumentRecord) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge_documents (
                    document_id, knowledge_base_id, tenant_id, filename,
                    original_filename, content_type, size_bytes, file_hash,
                    storage_path, status, parser_version, chunk_count, page_count,
                    error_message, created_by, created_at, updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                    $14, $15, $16, $17
                )
                ON CONFLICT (document_id) DO UPDATE SET
                    knowledge_base_id = EXCLUDED.knowledge_base_id,
                    tenant_id = EXCLUDED.tenant_id,
                    filename = EXCLUDED.filename,
                    original_filename = EXCLUDED.original_filename,
                    content_type = EXCLUDED.content_type,
                    size_bytes = EXCLUDED.size_bytes,
                    file_hash = EXCLUDED.file_hash,
                    storage_path = EXCLUDED.storage_path,
                    status = EXCLUDED.status,
                    parser_version = EXCLUDED.parser_version,
                    chunk_count = EXCLUDED.chunk_count,
                    page_count = EXCLUDED.page_count,
                    error_message = EXCLUDED.error_message,
                    created_by = EXCLUDED.created_by,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at
                """,
                document.document_id,
                document.knowledge_base_id,
                document.tenant_id,
                document.filename,
                document.original_filename,
                document.content_type,
                document.size_bytes,
                document.file_hash,
                document.storage_path,
                document.status,
                document.parser_version,
                document.chunk_count,
                document.page_count,
                document.error_message,
                document.created_by,
                document.created_at,
                document.updated_at,
            )

    async def list_documents(self, knowledge_base_id: str) -> list[DocumentRecord]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM knowledge_documents
                WHERE knowledge_base_id = $1
                ORDER BY created_at DESC
                """,
                knowledge_base_id,
            )
        return [DocumentRecord.from_dict(dict(row)) for row in rows]

    async def clear_documents(self, knowledge_base_id: str) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM knowledge_documents WHERE knowledge_base_id = $1",
                knowledge_base_id,
            )

    async def _require_pool(self):
        if self._pool is None:
            await self.connect()
        return self._pool


_postgres_repositories: dict[int, PostgresKnowledgeBaseRepository] = {}


async def get_knowledge_base_repository() -> KnowledgeBaseRepository:
    if settings.knowledge_metadata_backend == "postgres":
        dsn = settings.secret_value(settings.postgres_dsn)
        if not dsn:
            raise ConfigurationError(
                "KNOWLEDGE_METADATA_BACKEND=postgres 时必须配置 POSTGRES_DSN。"
            )
        loop_id = id(asyncio.get_running_loop())
        repository = _postgres_repositories.get(loop_id)
        if repository is None:
            repository = PostgresKnowledgeBaseRepository(dsn)
            _postgres_repositories[loop_id] = repository
            await repository.connect()
        return repository

    redis = await get_redis()
    return RedisKnowledgeBaseRepository(redis)

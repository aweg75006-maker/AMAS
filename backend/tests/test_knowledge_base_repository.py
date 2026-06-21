import asyncio

import pytest

from app.models.domain import DocumentRecord, KnowledgeBase, KnowledgeBaseVisibility
from app.repositories import knowledge_base_repository
from app.repositories.knowledge_base_repository import PostgresKnowledgeBaseRepository


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.rows = {}

    async def execute(self, sql, *args):
        self.executed.append((sql, args))

    async def fetchrow(self, sql, *args):
        self.last_fetchrow_sql = sql
        self.last_fetchrow_args = args
        return self.rows.get("fetchrow")

    async def fetch(self, sql, *args):
        self.last_fetch_sql = sql
        self.last_fetch_args = args
        return self.rows.get("fetch", [])


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


@pytest.mark.asyncio
async def test_postgres_repository_migrate_uses_alembic_entrypoint(monkeypatch):
    calls = []
    repository = PostgresKnowledgeBaseRepository("postgresql://example")

    def fake_run_migrations(dsn):
        calls.append(dsn)

    monkeypatch.setattr(
        knowledge_base_repository,
        "run_postgres_migrations",
        fake_run_migrations,
    )

    await repository.migrate()

    assert calls == ["postgresql://example"]


@pytest.mark.asyncio
async def test_postgres_repository_maps_knowledge_base_rows():
    conn = FakeConnection()
    conn.rows["fetchrow"] = {
        "knowledge_base_id": "kb_1",
        "tenant_id": "default",
        "name": "研发资料",
        "description": "",
        "visibility": KnowledgeBaseVisibility.TEAM.value,
        "embedding_model": "text-embedding-v4",
        "chunking_strategy": "recursive_character",
        "created_by": "",
        "created_at": 1.0,
        "updated_at": 2.0,
        "status": "active",
    }
    repository = PostgresKnowledgeBaseRepository("postgresql://example")
    repository._pool = FakePool(conn)

    kb = await repository.get_knowledge_base("kb_1")

    assert kb is not None
    assert kb.knowledge_base_id == "kb_1"
    assert kb.name == "研发资料"


@pytest.mark.asyncio
async def test_postgres_repository_save_methods_use_upserts():
    conn = FakeConnection()
    repository = PostgresKnowledgeBaseRepository("postgresql://example")
    repository._pool = FakePool(conn)

    await repository.save_knowledge_base(
        KnowledgeBase(
            knowledge_base_id="kb_1",
            tenant_id="default",
            name="研发资料",
        )
    )
    await repository.save_document(
        DocumentRecord(
            document_id="doc_1",
            knowledge_base_id="kb_1",
            tenant_id="default",
            filename="report.pdf",
        )
    )

    joined_sql = "\n".join(sql for sql, _args in conn.executed)
    assert "ON CONFLICT (knowledge_base_id) DO UPDATE" in joined_sql
    assert "ON CONFLICT (document_id) DO UPDATE" in joined_sql


def test_postgres_repository_cache_is_event_loop_scoped(monkeypatch):
    instances = []

    class FakePostgresRepository:
        backend_name = "postgres"

        def __init__(self, dsn):
            self.dsn = dsn
            instances.append(self)

        async def connect(self):
            return None

    class FakeSettings:
        knowledge_metadata_backend = "postgres"
        postgres_dsn = object()

        def secret_value(self, value):
            return "postgresql://example"

    monkeypatch.setattr(knowledge_base_repository, "settings", FakeSettings())
    monkeypatch.setattr(
        knowledge_base_repository,
        "PostgresKnowledgeBaseRepository",
        FakePostgresRepository,
    )
    knowledge_base_repository._postgres_repositories.clear()

    loop_one = asyncio.new_event_loop()
    loop_two = asyncio.new_event_loop()
    try:
        repo_one = loop_one.run_until_complete(
            knowledge_base_repository.get_knowledge_base_repository()
        )
        repo_two = loop_two.run_until_complete(
            knowledge_base_repository.get_knowledge_base_repository()
        )
    finally:
        loop_one.close()
        loop_two.close()
        knowledge_base_repository._postgres_repositories.clear()

    assert repo_one is not repo_two
    assert len(instances) == 2

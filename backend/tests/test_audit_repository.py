import pytest

from app.models.domain import AuditAction, AuditLog
from app.repositories.audit_repository import PostgresAuditRepository
from tests.test_knowledge_base_repository import FakeConnection, FakePool


@pytest.mark.asyncio
async def test_postgres_audit_repository_saves_json_details():
    conn = FakeConnection()
    repository = PostgresAuditRepository("postgresql://example")
    repository._pool = FakePool(conn)

    await repository.save_audit_log(
        AuditLog(
            audit_id="audit_1",
            action=AuditAction.KNOWLEDGE_BASE_CREATED.value,
            tenant_id="tenant_1",
            actor_user_id="user_1",
            target_type="knowledge_base",
            target_id="kb_1",
            details={"name": "研发资料"},
            created_at=1.0,
        )
    )

    sql, args = conn.executed[0]
    assert "INSERT INTO audit_logs" in sql
    assert args[0] == "audit_1"
    assert args[9] == '{"name": "研发资料"}'


@pytest.mark.asyncio
async def test_postgres_audit_repository_lists_logs_for_tenant():
    conn = FakeConnection()
    conn.rows["fetch"] = [
        {
            "audit_id": "audit_1",
            "action": AuditAction.MEMBER_CREATED.value,
            "tenant_id": "tenant_1",
            "actor_user_id": "user_owner",
            "actor_username": "owner",
            "target_type": "user",
            "target_id": "user_member",
            "status": "success",
            "request_id": "req_1",
            "details": {"role": "member"},
            "created_at": 1.0,
        }
    ]
    repository = PostgresAuditRepository("postgresql://example")
    repository._pool = FakePool(conn)

    logs = await repository.list_audit_logs_for_tenant("tenant_1")

    assert len(logs) == 1
    assert logs[0].action == AuditAction.MEMBER_CREATED.value
    assert logs[0].details == {"role": "member"}


@pytest.mark.asyncio
async def test_postgres_audit_repository_applies_optional_filters():
    conn = FakeConnection()
    repository = PostgresAuditRepository("postgresql://example")
    repository._pool = FakePool(conn)

    await repository.list_audit_logs_for_tenant(
        "tenant_1",
        limit=25,
        action=AuditAction.LOGIN_SUCCEEDED.value,
        actor_user_id="user_1",
    )

    sql = conn.last_fetch_sql
    args = conn.last_fetch_args
    assert "tenant_id = $1" in sql
    assert "action = $2" in sql
    assert "actor_user_id = $3" in sql
    assert "LIMIT $4" in sql
    assert args == (
        "tenant_1",
        AuditAction.LOGIN_SUCCEEDED.value,
        "user_1",
        25,
    )

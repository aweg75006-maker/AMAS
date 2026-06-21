import pytest

from app.models.domain import Tenant, TenantMembership, TenantRole, UserAccount
from app.repositories.account_repository import PostgresAccountRepository
from tests.test_knowledge_base_repository import FakePool, FakeConnection


@pytest.mark.asyncio
async def test_postgres_account_repository_save_methods_use_upserts():
    conn = FakeConnection()
    repository = PostgresAccountRepository("postgresql://example")
    repository._pool = FakePool(conn)

    await repository.save_tenant(
        Tenant(
            tenant_id="tenant_1",
            name="Acme",
            slug="acme",
        )
    )
    await repository.save_user(
        UserAccount(
            user_id="user_1",
            username="user1",
            email="User@Example.com",
            password_hash="hash",
        )
    )
    await repository.save_membership(
        TenantMembership(
            membership_id="membership_1",
            tenant_id="tenant_1",
            user_id="user_1",
            role=TenantRole.OWNER.value,
        )
    )

    joined_sql = "\n".join(sql for sql, _args in conn.executed)
    assert "ON CONFLICT (tenant_id) DO UPDATE" in joined_sql
    assert "ON CONFLICT (user_id) DO UPDATE" in joined_sql
    assert "ON CONFLICT (tenant_id, user_id) DO UPDATE" in joined_sql
    assert "username" in joined_sql


@pytest.mark.asyncio
async def test_postgres_account_repository_maps_rows():
    conn = FakeConnection()
    conn.rows["fetchrow"] = {
        "tenant_id": "tenant_1",
        "name": "Acme",
        "slug": "acme",
        "status": "active",
        "created_at": 1.0,
        "updated_at": 2.0,
    }
    repository = PostgresAccountRepository("postgresql://example")
    repository._pool = FakePool(conn)

    tenant = await repository.get_tenant("tenant_1")

    assert tenant is not None
    assert tenant.slug == "acme"


@pytest.mark.asyncio
async def test_postgres_account_repository_lists_memberships_for_tenant():
    conn = FakeConnection()
    conn.rows["fetch"] = [
        {
            "membership_id": "membership_1",
            "tenant_id": "tenant_1",
            "user_id": "user_1",
            "role": TenantRole.MEMBER.value,
            "status": "active",
            "created_at": 1.0,
            "updated_at": 2.0,
        }
    ]
    repository = PostgresAccountRepository("postgresql://example")
    repository._pool = FakePool(conn)

    memberships = await repository.list_memberships_for_tenant("tenant_1")

    assert len(memberships) == 1
    assert memberships[0].tenant_id == "tenant_1"
    assert memberships[0].role == TenantRole.MEMBER.value

from __future__ import annotations

import asyncio
from typing import Protocol

from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.db.migrations import run_postgres_migrations
from app.models.domain import Tenant, TenantMembership, UserAccount


class AccountRepository(Protocol):
    backend_name: str

    async def ping(self) -> bool:
        ...

    async def save_tenant(self, tenant: Tenant) -> None:
        ...

    async def get_tenant(self, tenant_id: str) -> Tenant | None:
        ...

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        ...

    async def save_user(self, user: UserAccount) -> None:
        ...

    async def get_user(self, user_id: str) -> UserAccount | None:
        ...

    async def get_user_by_email(self, email: str) -> UserAccount | None:
        ...

    async def get_user_by_username(self, username: str) -> UserAccount | None:
        ...

    async def save_membership(self, membership: TenantMembership) -> None:
        ...

    async def get_membership(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> TenantMembership | None:
        ...

    async def list_memberships_for_tenant(
        self,
        tenant_id: str,
    ) -> list[TenantMembership]:
        ...

    async def list_memberships_for_user(self, user_id: str) -> list[TenantMembership]:
        ...


class PostgresAccountRepository:
    """PostgreSQL repository for tenants, users, and tenant memberships."""

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
                "缺少 asyncpg，无法启用 PostgreSQL 账号存储。请安装 backend/requirements.txt。"
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

    async def save_tenant(self, tenant: Tenant) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tenants (
                    tenant_id, name, slug, status, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (tenant_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    slug = EXCLUDED.slug,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
                """,
                tenant.tenant_id,
                tenant.name,
                tenant.slug,
                tenant.status,
                tenant.created_at,
                tenant.updated_at,
            )

    async def get_tenant(self, tenant_id: str) -> Tenant | None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM tenants WHERE tenant_id = $1",
                tenant_id,
            )
        return Tenant.from_dict(dict(row)) if row else None

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM tenants WHERE slug = $1",
                slug,
            )
        return Tenant.from_dict(dict(row)) if row else None

    async def save_user(self, user: UserAccount) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (
                    user_id, username, email, display_name, password_hash, status,
                    created_at, updated_at, last_login_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    email = EXCLUDED.email,
                    display_name = EXCLUDED.display_name,
                    password_hash = EXCLUDED.password_hash,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at,
                    last_login_at = EXCLUDED.last_login_at
                """,
                user.user_id,
                user.username.lower(),
                user.email.lower(),
                user.display_name,
                user.password_hash,
                user.status,
                user.created_at,
                user.updated_at,
                user.last_login_at,
            )

    async def get_user(self, user_id: str) -> UserAccount | None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1",
                user_id,
            )
        return UserAccount.from_dict(dict(row)) if row else None

    async def get_user_by_email(self, email: str) -> UserAccount | None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE email = $1",
                email.lower(),
            )
        return UserAccount.from_dict(dict(row)) if row else None

    async def get_user_by_username(self, username: str) -> UserAccount | None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE username = $1",
                username.lower(),
            )
        return UserAccount.from_dict(dict(row)) if row else None

    async def save_membership(self, membership: TenantMembership) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tenant_memberships (
                    membership_id, tenant_id, user_id, role, status,
                    created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                    role = EXCLUDED.role,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
                """,
                membership.membership_id,
                membership.tenant_id,
                membership.user_id,
                membership.role,
                membership.status,
                membership.created_at,
                membership.updated_at,
            )

    async def get_membership(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> TenantMembership | None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM tenant_memberships
                WHERE tenant_id = $1 AND user_id = $2
                """,
                tenant_id,
                user_id,
            )
        return TenantMembership.from_dict(dict(row)) if row else None

    async def list_memberships_for_tenant(
        self,
        tenant_id: str,
    ) -> list[TenantMembership]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM tenant_memberships
                WHERE tenant_id = $1
                ORDER BY created_at DESC
                """,
                tenant_id,
            )
        return [TenantMembership.from_dict(dict(row)) for row in rows]

    async def list_memberships_for_user(self, user_id: str) -> list[TenantMembership]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM tenant_memberships
                WHERE user_id = $1
                ORDER BY created_at DESC
                """,
                user_id,
            )
        return [TenantMembership.from_dict(dict(row)) for row in rows]

    async def _require_pool(self):
        if self._pool is None:
            await self.connect()
        return self._pool


_postgres_account_repositories: dict[int, PostgresAccountRepository] = {}


async def get_account_repository() -> AccountRepository:
    dsn = settings.secret_value(settings.postgres_dsn)
    if not dsn:
        raise ConfigurationError("账号存储需要配置 POSTGRES_DSN。")

    loop_id = id(asyncio.get_running_loop())
    repository = _postgres_account_repositories.get(loop_id)
    if repository is None:
        repository = PostgresAccountRepository(dsn)
        _postgres_account_repositories[loop_id] = repository
        await repository.connect()
    return repository

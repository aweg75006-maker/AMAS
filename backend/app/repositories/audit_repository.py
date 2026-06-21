from __future__ import annotations

import asyncio
import json
from typing import Protocol

from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.db.migrations import run_postgres_migrations
from app.models.domain import AuditLog


class AuditRepository(Protocol):
    backend_name: str

    async def save_audit_log(self, event: AuditLog) -> None:
        ...

    async def list_audit_logs_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        action: str | None = None,
        actor_user_id: str | None = None,
    ) -> list[AuditLog]:
        ...


class PostgresAuditRepository:
    """PostgreSQL repository for compliance and security audit logs."""

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
                "缺少 asyncpg，无法启用 PostgreSQL 审计日志存储。请安装 backend/requirements.txt。"
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

    async def save_audit_log(self, event: AuditLog) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_logs (
                    audit_id, action, tenant_id, actor_user_id, actor_username,
                    target_type, target_id, status, request_id, details, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
                ON CONFLICT (audit_id) DO NOTHING
                """,
                event.audit_id,
                event.action,
                event.tenant_id,
                event.actor_user_id,
                event.actor_username,
                event.target_type,
                event.target_id,
                event.status,
                event.request_id,
                json.dumps(event.details, ensure_ascii=False),
                event.created_at,
            )

    async def list_audit_logs_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        action: str | None = None,
        actor_user_id: str | None = None,
    ) -> list[AuditLog]:
        pool = await self._require_pool()
        filters = ["tenant_id = $1"]
        args: list[object] = [tenant_id]
        if action:
            args.append(action)
            filters.append(f"action = ${len(args)}")
        if actor_user_id:
            args.append(actor_user_id)
            filters.append(f"actor_user_id = ${len(args)}")
        args.append(limit)
        limit_param = f"${len(args)}"

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM audit_logs
                WHERE {" AND ".join(filters)}
                ORDER BY created_at DESC
                LIMIT {limit_param}
                """,
                *args,
            )
        return [AuditLog.from_dict(dict(row)) for row in rows]

    async def _require_pool(self):
        if self._pool is None:
            await self.connect()
        return self._pool


_postgres_audit_repositories: dict[int, PostgresAuditRepository] = {}


async def get_audit_repository() -> AuditRepository:
    dsn = settings.secret_value(settings.postgres_dsn)
    if not dsn:
        raise ConfigurationError("审计日志存储需要配置 POSTGRES_DSN。")

    loop_id = id(asyncio.get_running_loop())
    repository = _postgres_audit_repositories.get(loop_id)
    if repository is None:
        repository = PostgresAuditRepository(dsn)
        _postgres_audit_repositories[loop_id] = repository
        await repository.connect()
    return repository

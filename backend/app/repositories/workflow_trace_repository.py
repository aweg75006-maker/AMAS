from __future__ import annotations

import asyncio
import json
from typing import Protocol

from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.db.migrations import run_postgres_migrations
from app.models.domain import (
    ErrorEventRecord,
    WorkflowNodeRunRecord,
    WorkflowRunRecord,
    WorkflowToolRunRecord,
)


class WorkflowTraceRepository(Protocol):
    backend_name: str

    async def save_workflow_run(self, run: WorkflowRunRecord) -> None:
        ...

    async def save_node_run(self, node_run: WorkflowNodeRunRecord) -> None:
        ...

    async def save_tool_run(self, tool_run: WorkflowToolRunRecord) -> None:
        ...

    async def save_error_event(self, event: ErrorEventRecord) -> None:
        ...

    async def list_workflow_runs(self, tenant_id: str, *, limit: int = 50) -> list[WorkflowRunRecord]:
        ...

    async def get_workflow_run(self, run_id: str) -> WorkflowRunRecord | None:
        ...

    async def list_node_runs(self, run_id: str) -> list[WorkflowNodeRunRecord]:
        ...

    async def list_tool_runs(self, run_id: str) -> list[WorkflowToolRunRecord]:
        ...

    async def list_error_events(self, tenant_id: str, *, limit: int = 50) -> list[ErrorEventRecord]:
        ...


class PostgresWorkflowTraceRepository:
    """PostgreSQL repository for Agent workflow traces and error events."""

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
                "缺少 asyncpg，无法启用 PostgreSQL 工作流追踪存储。请安装 backend/requirements.txt。"
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

    async def save_workflow_run(self, run: WorkflowRunRecord) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, tenant_id, user_id, username, session_id, turn_id,
                    knowledge_base_id, request_id, query, search_mode, status,
                    started_at, finished_at, duration_ms, error_code, error_message,
                    metadata
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                    $14, $15, $16, $17::jsonb
                )
                ON CONFLICT (run_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    finished_at = EXCLUDED.finished_at,
                    duration_ms = EXCLUDED.duration_ms,
                    error_code = EXCLUDED.error_code,
                    error_message = EXCLUDED.error_message,
                    metadata = EXCLUDED.metadata
                """,
                run.run_id,
                run.tenant_id,
                run.user_id,
                run.username,
                run.session_id,
                run.turn_id,
                run.knowledge_base_id,
                run.request_id,
                run.query,
                run.search_mode,
                run.status,
                run.started_at,
                run.finished_at,
                run.duration_ms,
                run.error_code,
                run.error_message,
                json.dumps(run.metadata, ensure_ascii=False),
            )

    async def save_node_run(self, node_run: WorkflowNodeRunRecord) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workflow_node_runs (
                    node_run_id, run_id, node_name, tenant_id, session_id, turn_id,
                    status, started_at, finished_at, duration_ms, input_summary,
                    output_summary, token_usage, error_code, error_message, metadata
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                    $13::jsonb, $14, $15, $16::jsonb
                )
                ON CONFLICT (node_run_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    finished_at = EXCLUDED.finished_at,
                    duration_ms = EXCLUDED.duration_ms,
                    output_summary = EXCLUDED.output_summary,
                    token_usage = EXCLUDED.token_usage,
                    error_code = EXCLUDED.error_code,
                    error_message = EXCLUDED.error_message,
                    metadata = EXCLUDED.metadata
                """,
                node_run.node_run_id,
                node_run.run_id,
                node_run.node_name,
                node_run.tenant_id,
                node_run.session_id,
                node_run.turn_id,
                node_run.status,
                node_run.started_at,
                node_run.finished_at,
                node_run.duration_ms,
                node_run.input_summary,
                node_run.output_summary,
                json.dumps(node_run.token_usage, ensure_ascii=False),
                node_run.error_code,
                node_run.error_message,
                json.dumps(node_run.metadata, ensure_ascii=False),
            )

    async def save_tool_run(self, tool_run: WorkflowToolRunRecord) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workflow_tool_runs (
                    tool_run_id, run_id, node_name, tool_name, tenant_id, session_id,
                    turn_id, status, started_at, finished_at, duration_ms,
                    input_summary, output_summary, error_code, error_message, metadata
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                    $13, $14, $15, $16::jsonb
                )
                ON CONFLICT (tool_run_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    finished_at = EXCLUDED.finished_at,
                    duration_ms = EXCLUDED.duration_ms,
                    output_summary = EXCLUDED.output_summary,
                    error_code = EXCLUDED.error_code,
                    error_message = EXCLUDED.error_message,
                    metadata = EXCLUDED.metadata
                """,
                tool_run.tool_run_id,
                tool_run.run_id,
                tool_run.node_name,
                tool_run.tool_name,
                tool_run.tenant_id,
                tool_run.session_id,
                tool_run.turn_id,
                tool_run.status,
                tool_run.started_at,
                tool_run.finished_at,
                tool_run.duration_ms,
                tool_run.input_summary,
                tool_run.output_summary,
                tool_run.error_code,
                tool_run.error_message,
                json.dumps(tool_run.metadata, ensure_ascii=False),
            )

    async def save_error_event(self, event: ErrorEventRecord) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO error_events (
                    error_event_id, error_code, message, source, severity,
                    tenant_id, user_id, username, request_id, session_id, turn_id,
                    run_id, node_name, path, status_code, details, created_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                    $14, $15, $16::jsonb, $17
                )
                ON CONFLICT (error_event_id) DO NOTHING
                """,
                event.error_event_id,
                event.error_code,
                event.message,
                event.source,
                event.severity,
                event.tenant_id,
                event.user_id,
                event.username,
                event.request_id,
                event.session_id,
                event.turn_id,
                event.run_id,
                event.node_name,
                event.path,
                event.status_code,
                json.dumps(event.details, ensure_ascii=False),
                event.created_at,
            )

    async def list_workflow_runs(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
    ) -> list[WorkflowRunRecord]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM workflow_runs
                WHERE tenant_id = $1
                ORDER BY started_at DESC
                LIMIT $2
                """,
                tenant_id,
                limit,
            )
        return [WorkflowRunRecord.from_dict(dict(row)) for row in rows]

    async def get_workflow_run(self, run_id: str) -> WorkflowRunRecord | None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM workflow_runs WHERE run_id = $1",
                run_id,
            )
        return WorkflowRunRecord.from_dict(dict(row)) if row else None

    async def list_node_runs(self, run_id: str) -> list[WorkflowNodeRunRecord]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM workflow_node_runs
                WHERE run_id = $1
                ORDER BY started_at ASC
                """,
                run_id,
            )
        return [WorkflowNodeRunRecord.from_dict(dict(row)) for row in rows]

    async def list_tool_runs(self, run_id: str) -> list[WorkflowToolRunRecord]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM workflow_tool_runs
                WHERE run_id = $1
                ORDER BY started_at ASC
                """,
                run_id,
            )
        return [WorkflowToolRunRecord.from_dict(dict(row)) for row in rows]

    async def list_error_events(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
    ) -> list[ErrorEventRecord]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM error_events
                WHERE tenant_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                tenant_id,
                limit,
            )
        return [ErrorEventRecord.from_dict(dict(row)) for row in rows]

    async def _require_pool(self):
        if self._pool is None:
            await self.connect()
        return self._pool


_postgres_workflow_trace_repositories: dict[int, PostgresWorkflowTraceRepository] = {}


async def get_workflow_trace_repository() -> WorkflowTraceRepository:
    dsn = settings.secret_value(settings.postgres_dsn)
    if not dsn:
        raise ConfigurationError("工作流追踪存储需要配置 POSTGRES_DSN。")

    loop_id = id(asyncio.get_running_loop())
    repository = _postgres_workflow_trace_repositories.get(loop_id)
    if repository is None:
        repository = PostgresWorkflowTraceRepository(dsn)
        _postgres_workflow_trace_repositories[loop_id] = repository
        await repository.connect()
    return repository

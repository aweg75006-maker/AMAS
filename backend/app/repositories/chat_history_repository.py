from __future__ import annotations

import asyncio
import json
from typing import Protocol

from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.db.migrations import run_postgres_migrations
from app.models.domain import ChatSessionRecord, ChatTurnRecord


class ChatHistoryRepository(Protocol):
    backend_name: str

    async def save_session(self, session: ChatSessionRecord) -> None:
        ...

    async def save_turn(self, turn: ChatTurnRecord) -> None:
        ...

    async def get_session(self, session_id: str) -> ChatSessionRecord | None:
        ...

    async def list_sessions(
        self,
        tenant_id: str,
        *,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[ChatSessionRecord]:
        ...

    async def list_turns(
        self,
        session_id: str,
        *,
        limit: int = 50,
    ) -> list[ChatTurnRecord]:
        ...


class InMemoryChatHistoryRepository:
    """Process-local chat history store for local development and tests."""

    backend_name = "memory"

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSessionRecord] = {}
        self._turns: dict[str, dict[str, ChatTurnRecord]] = {}

    async def save_session(self, session: ChatSessionRecord) -> None:
        self._sessions[session.session_id] = session

    async def save_turn(self, turn: ChatTurnRecord) -> None:
        self._turns.setdefault(turn.session_id, {})[turn.turn_id] = turn

    async def get_session(self, session_id: str) -> ChatSessionRecord | None:
        return self._sessions.get(session_id)

    async def list_sessions(
        self,
        tenant_id: str,
        *,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[ChatSessionRecord]:
        sessions = [
            session
            for session in self._sessions.values()
            if session.tenant_id == tenant_id and (not user_id or session.user_id == user_id)
        ]
        sessions.sort(key=lambda session: session.updated_at, reverse=True)
        return sessions[:limit]

    async def list_turns(
        self,
        session_id: str,
        *,
        limit: int = 50,
    ) -> list[ChatTurnRecord]:
        turns = list(self._turns.get(session_id, {}).values())
        turns.sort(key=lambda turn: turn.turn_number, reverse=True)
        return turns[:limit]


class PostgresChatHistoryRepository:
    """PostgreSQL repository for durable chat session history."""

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
                "缺少 asyncpg，无法启用 PostgreSQL 会话历史存储。请安装 backend/requirements.txt。"
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

    async def save_session(self, session: ChatSessionRecord) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO chat_sessions (
                    session_id, tenant_id, user_id, username, knowledge_base_id,
                    title, status, turns_count, total_budget, total_estimated_tokens,
                    total_actual_tokens, compression_savings, created_at, updated_at,
                    last_active
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                    $14, $15
                )
                ON CONFLICT (session_id) DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id,
                    user_id = EXCLUDED.user_id,
                    username = EXCLUDED.username,
                    knowledge_base_id = EXCLUDED.knowledge_base_id,
                    title = COALESCE(NULLIF(chat_sessions.title, ''), EXCLUDED.title),
                    status = EXCLUDED.status,
                    turns_count = EXCLUDED.turns_count,
                    total_budget = EXCLUDED.total_budget,
                    total_estimated_tokens = EXCLUDED.total_estimated_tokens,
                    total_actual_tokens = EXCLUDED.total_actual_tokens,
                    compression_savings = EXCLUDED.compression_savings,
                    updated_at = EXCLUDED.updated_at,
                    last_active = EXCLUDED.last_active
                """,
                session.session_id,
                session.tenant_id,
                session.user_id,
                session.username,
                session.knowledge_base_id,
                session.title,
                session.status,
                session.turns_count,
                session.total_budget,
                session.total_estimated_tokens,
                session.total_actual_tokens,
                session.compression_savings,
                session.created_at,
                session.updated_at,
                session.last_active,
            )

    async def save_turn(self, turn: ChatTurnRecord) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO chat_turns (
                    turn_id, session_id, tenant_id, user_id, username,
                    knowledge_base_id, turn_number, query, search_mode, plan,
                    search_results, final_report, critique, review_status,
                    token_usage, created_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb,
                    $11::jsonb, $12, $13, $14, $15::jsonb, $16
                )
                ON CONFLICT (turn_id) DO UPDATE SET
                    session_id = EXCLUDED.session_id,
                    tenant_id = EXCLUDED.tenant_id,
                    user_id = EXCLUDED.user_id,
                    username = EXCLUDED.username,
                    knowledge_base_id = EXCLUDED.knowledge_base_id,
                    turn_number = EXCLUDED.turn_number,
                    query = EXCLUDED.query,
                    search_mode = EXCLUDED.search_mode,
                    plan = EXCLUDED.plan,
                    search_results = EXCLUDED.search_results,
                    final_report = EXCLUDED.final_report,
                    critique = EXCLUDED.critique,
                    review_status = EXCLUDED.review_status,
                    token_usage = EXCLUDED.token_usage,
                    created_at = EXCLUDED.created_at
                """,
                turn.turn_id,
                turn.session_id,
                turn.tenant_id,
                turn.user_id,
                turn.username,
                turn.knowledge_base_id,
                turn.turn_number,
                turn.query,
                turn.search_mode,
                json.dumps(turn.plan, ensure_ascii=False),
                json.dumps(turn.search_results, ensure_ascii=False),
                turn.final_report,
                turn.critique,
                turn.review_status,
                json.dumps(turn.token_usage, ensure_ascii=False),
                turn.created_at,
            )

    async def get_session(self, session_id: str) -> ChatSessionRecord | None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM chat_sessions WHERE session_id = $1",
                session_id,
            )
        return ChatSessionRecord.from_dict(dict(row)) if row else None

    async def list_sessions(
        self,
        tenant_id: str,
        *,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[ChatSessionRecord]:
        pool = await self._require_pool()
        filters = ["tenant_id = $1"]
        args: list[object] = [tenant_id]
        if user_id:
            args.append(user_id)
            filters.append(f"user_id = ${len(args)}")
        args.append(limit)
        limit_param = f"${len(args)}"
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM chat_sessions
                WHERE {" AND ".join(filters)}
                ORDER BY updated_at DESC
                LIMIT {limit_param}
                """,
                *args,
            )
        return [ChatSessionRecord.from_dict(dict(row)) for row in rows]

    async def list_turns(
        self,
        session_id: str,
        *,
        limit: int = 50,
    ) -> list[ChatTurnRecord]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM chat_turns
                WHERE session_id = $1
                ORDER BY turn_number DESC
                LIMIT $2
                """,
                session_id,
                limit,
            )
        return [ChatTurnRecord.from_dict(dict(row)) for row in rows]

    async def _require_pool(self):
        if self._pool is None:
            await self.connect()
        return self._pool


_postgres_chat_history_repositories: dict[int, PostgresChatHistoryRepository] = {}
_memory_chat_history_repository = InMemoryChatHistoryRepository()


async def get_chat_history_repository() -> ChatHistoryRepository:
    if settings.chat_history_backend == "memory":
        return _memory_chat_history_repository

    dsn = settings.secret_value(settings.postgres_dsn)
    if not dsn:
        raise ConfigurationError("会话历史存储需要配置 POSTGRES_DSN。")

    loop_id = id(asyncio.get_running_loop())
    repository = _postgres_chat_history_repositories.get(loop_id)
    if repository is None:
        repository = PostgresChatHistoryRepository(dsn)
        _postgres_chat_history_repositories[loop_id] = repository
        await repository.connect()
    return repository

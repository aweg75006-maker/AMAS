from __future__ import annotations

import time

from app.core.identity import RequestContext
from app.core.logging import get_logger
from app.models.domain import (
    ChatSessionRecord,
    ChatSessionStatus,
    ChatTurnRecord,
    SessionMeta,
    TurnRecord,
)
from app.repositories.chat_history_repository import (
    ChatHistoryRepository,
    get_chat_history_repository,
)
from app.utils.budget_ledger import BudgetSnapshot


logger = get_logger("iris.chat_history")


class ChatHistoryService:
    """Persists completed chat turns through the configured history repository."""

    def __init__(self, repository: ChatHistoryRepository):
        self.repository = repository

    async def persist_completed_turn(
        self,
        *,
        session_meta: SessionMeta,
        turn_record: TurnRecord,
        context: RequestContext,
        knowledge_base_id: str,
        snapshot: BudgetSnapshot,
    ) -> tuple[ChatSessionRecord, ChatTurnRecord]:
        now = time.time()
        title = self._title_from_query(turn_record.query)
        session = ChatSessionRecord(
            session_id=session_meta.session_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            username=context.username,
            knowledge_base_id=knowledge_base_id,
            title=title,
            status=ChatSessionStatus.ACTIVE.value,
            turns_count=session_meta.turns_count,
            total_budget=session_meta.total_budget,
            total_estimated_tokens=snapshot.session_estimated_total,
            total_actual_tokens=snapshot.session_actual_total,
            compression_savings=snapshot.compression_savings,
            created_at=session_meta.created_at,
            updated_at=now,
            last_active=session_meta.last_active,
        )
        turn = ChatTurnRecord(
            turn_id=turn_record.turn_id,
            session_id=session_meta.session_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            username=context.username,
            knowledge_base_id=knowledge_base_id,
            turn_number=turn_record.turn_number,
            query=turn_record.query,
            search_mode=turn_record.search_mode,
            plan=turn_record.plan,
            search_results=turn_record.search_results,
            final_report=turn_record.final_report,
            critique=turn_record.critique,
            review_status=turn_record.review_status,
            token_usage=turn_record.token_usage,
            created_at=turn_record.timestamp,
        )
        await self.repository.save_session(session)
        await self.repository.save_turn(turn)
        return session, turn

    async def list_sessions(
        self,
        *,
        tenant_id: str,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[ChatSessionRecord]:
        safe_limit = max(1, min(limit, 200))
        return await self.repository.list_sessions(
            tenant_id,
            user_id=user_id,
            limit=safe_limit,
        )

    async def get_session_with_turns(
        self,
        *,
        tenant_id: str,
        session_id: str,
        limit: int = 50,
    ) -> tuple[ChatSessionRecord, list[ChatTurnRecord]] | None:
        session = await self.repository.get_session(session_id)
        if session is None or session.tenant_id != tenant_id:
            return None
        turns = await self.repository.list_turns(
            session_id,
            limit=max(1, min(limit, 200)),
        )
        return session, turns

    def _title_from_query(self, query: str) -> str:
        title = " ".join(query.strip().split())
        return title[:80] or "Untitled session"


async def get_chat_history_service() -> ChatHistoryService:
    repository = await get_chat_history_repository()
    return ChatHistoryService(repository)


async def persist_completed_chat_turn(**kwargs) -> tuple[ChatSessionRecord, ChatTurnRecord] | None:
    try:
        service = await get_chat_history_service()
        return await service.persist_completed_turn(**kwargs)
    except Exception:
        logger.exception(
            "chat_history_persist_failed",
            extra={
                "session_id": getattr(kwargs.get("session_meta"), "session_id", ""),
                "turn_id": getattr(kwargs.get("turn_record"), "turn_id", ""),
            },
        )
        return None

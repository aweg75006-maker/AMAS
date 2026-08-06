import pytest
from uuid import uuid4

from app.models.domain import SessionMeta, TurnRecord
from app.repositories.chat_history_repository import InMemoryChatHistoryRepository
from app.services.chat_history_service import ChatHistoryService
from app.utils.budget_ledger import BudgetSnapshot


@pytest.mark.asyncio
async def test_chat_history_service_persists_completed_turn_in_memory():
    repository = InMemoryChatHistoryRepository()
    service = ChatHistoryService(repository)
    suffix = uuid4().hex[:10]
    session_id = f"iris_history_{suffix}"

    session_meta = SessionMeta(
        session_id=session_id,
        turns_count=1,
        total_budget=128000,
    )
    turn_record = TurnRecord(
        turn_id=f"turn_{suffix}",
        turn_number=1,
        query="测试历史持久化",
        final_report="报告内容",
        token_usage={"estimated_input": 12},
    )
    snapshot = BudgetSnapshot(
        session_id=session_id,
        turn_number=1,
        session_estimated_total=12,
        session_actual_total=0,
    )

    await service.persist_completed_turn(
        session_meta=session_meta,
        turn_record=turn_record,
        knowledge_base_id="kb_history",
        snapshot=snapshot,
    )
    sessions = await service.list_sessions()
    result = await service.get_session_with_turns(
        session_id=session_id,
    )

    assert any(session.session_id == session_id for session in sessions)
    assert result is not None
    session, turns = result
    assert session.title == "测试历史持久化"
    assert turns[0].final_report == "报告内容"

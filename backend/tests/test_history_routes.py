import asyncio
from uuid import uuid4

from app.models.domain import SessionMeta, TurnRecord
from app.services.chat_history_service import get_chat_history_service
from app.utils.budget_ledger import BudgetSnapshot


def _persist_history_session() -> str:
    suffix = uuid4().hex[:10]
    session_id = f"iris_route_{suffix}"

    async def persist():
        service = await get_chat_history_service()
        await service.persist_completed_turn(
            session_meta=SessionMeta(session_id=session_id, turns_count=1),
            turn_record=TurnRecord(
                turn_id=f"turn_{suffix}",
                turn_number=1,
                query="路由历史测试",
                final_report="历史报告",
            ),
            knowledge_base_id="kb_history",
            snapshot=BudgetSnapshot(session_id=session_id, turn_number=1),
        )

    asyncio.run(persist())
    return session_id


def test_history_routes_expose_single_user_memory(client):
    session_id = _persist_history_session()

    sessions = client.get("/api/history/sessions")
    detail = client.get(f"/api/history/sessions/{session_id}")

    assert sessions.status_code == 200
    assert any(item["session_id"] == session_id for item in sessions.json()["items"])
    assert detail.status_code == 200
    assert detail.json()["turns"][0]["final_report"] == "历史报告"

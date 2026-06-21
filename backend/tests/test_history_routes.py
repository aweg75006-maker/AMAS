import asyncio
from uuid import uuid4

from app.core.config import settings
from app.core.identity import RequestContext
from app.core.security import create_access_token
from app.models.domain import SessionMeta, TenantRole, TurnRecord
from app.repositories.chat_history_repository import PostgresChatHistoryRepository
from app.services.chat_history_service import ChatHistoryService
from app.utils.budget_ledger import BudgetSnapshot


def _persist_history_session(
    *,
    tenant_id: str,
    user_id: str,
    username: str = "history",
):
    dsn = settings.secret_value(settings.postgres_dsn)
    assert dsn
    suffix = uuid4().hex[:10]
    session_id = f"iris_route_{suffix}"

    async def persist():
        repository = PostgresChatHistoryRepository(dsn)
        await repository.connect()
        try:
            service = ChatHistoryService(repository)
            await service.persist_completed_turn(
                session_meta=SessionMeta(
                    session_id=session_id,
                    turns_count=1,
                    total_budget=128000,
                ),
                turn_record=TurnRecord(
                    turn_id=f"turn_{suffix}",
                    turn_number=1,
                    query="路由历史测试",
                    final_report="历史报告",
                ),
                context=RequestContext(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    username=username,
                    role=TenantRole.MEMBER.value,
                    auth_source="jwt",
                ),
                knowledge_base_id="kb_history",
                snapshot=BudgetSnapshot(session_id=session_id, turn_number=1),
            )
        finally:
            await repository.close()

    asyncio.run(persist())
    return session_id


def test_history_sessions_list_mine_scope(client):
    session_id = _persist_history_session(
        tenant_id="tenant_history_route",
        user_id="user_history_route",
    )
    token = create_access_token(
        user_id="user_history_route",
        username="history",
        tenant_id="tenant_history_route",
        role=TenantRole.MEMBER.value,
        expires_in=60,
    )

    response = client.get(
        "/api/history/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "mine"
    assert any(item["session_id"] == session_id for item in body["items"])


def test_history_session_detail_hides_other_tenant(client):
    session_id = _persist_history_session(
        tenant_id="tenant_history_a",
        user_id="user_history_a",
    )
    token = create_access_token(
        user_id="user_history_a",
        username="history",
        tenant_id="tenant_history_b",
        role=TenantRole.OWNER.value,
        expires_in=60,
    )

    response = client.get(
        f"/api/history/sessions/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HISTORY_SESSION_NOT_FOUND"


def test_owner_can_list_tenant_history_scope(client):
    session_id = _persist_history_session(
        tenant_id="tenant_history_owner",
        user_id="user_member_history",
    )
    token = create_access_token(
        user_id="user_owner_history",
        username="owner",
        tenant_id="tenant_history_owner",
        role=TenantRole.OWNER.value,
        expires_in=60,
    )

    response = client.get(
        "/api/history/sessions",
        params={"scope": "tenant"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "tenant"
    assert any(item["session_id"] == session_id for item in body["items"])

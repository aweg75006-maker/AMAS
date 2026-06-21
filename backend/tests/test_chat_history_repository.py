import pytest

from app.models.domain import ChatSessionRecord, ChatTurnRecord
from app.repositories.chat_history_repository import PostgresChatHistoryRepository
from tests.test_knowledge_base_repository import FakeConnection, FakePool


@pytest.mark.asyncio
async def test_postgres_chat_history_repository_save_methods_use_upserts():
    conn = FakeConnection()
    repository = PostgresChatHistoryRepository("postgresql://example")
    repository._pool = FakePool(conn)

    await repository.save_session(
        ChatSessionRecord(
            session_id="iris_1",
            tenant_id="tenant_1",
            user_id="user_1",
            title="测试会话",
        )
    )
    await repository.save_turn(
        ChatTurnRecord(
            turn_id="turn_1",
            session_id="iris_1",
            tenant_id="tenant_1",
            query="hello",
            plan=["step"],
            token_usage={"estimated_input": 1},
        )
    )

    joined_sql = "\n".join(sql for sql, _args in conn.executed)
    assert "INSERT INTO chat_sessions" in joined_sql
    assert "ON CONFLICT (session_id) DO UPDATE" in joined_sql
    assert "INSERT INTO chat_turns" in joined_sql
    assert "ON CONFLICT (turn_id) DO UPDATE" in joined_sql
    assert conn.executed[1][1][9] == '["step"]'
    assert conn.executed[1][1][14] == '{"estimated_input": 1}'


@pytest.mark.asyncio
async def test_postgres_chat_history_repository_lists_sessions_with_filters():
    conn = FakeConnection()
    conn.rows["fetch"] = [
        {
            "session_id": "iris_1",
            "tenant_id": "tenant_1",
            "user_id": "user_1",
            "username": "owner",
            "knowledge_base_id": "kb_1",
            "title": "测试会话",
            "status": "active",
            "turns_count": 1,
            "total_budget": 128000,
            "total_estimated_tokens": 2,
            "total_actual_tokens": 0,
            "compression_savings": 0,
            "created_at": 1.0,
            "updated_at": 2.0,
            "last_active": 2.0,
        }
    ]
    repository = PostgresChatHistoryRepository("postgresql://example")
    repository._pool = FakePool(conn)

    sessions = await repository.list_sessions(
        "tenant_1",
        user_id="user_1",
        limit=10,
    )

    assert len(sessions) == 1
    assert sessions[0].session_id == "iris_1"
    assert "tenant_id = $1" in conn.last_fetch_sql
    assert "user_id = $2" in conn.last_fetch_sql
    assert conn.last_fetch_args == ("tenant_1", "user_1", 10)

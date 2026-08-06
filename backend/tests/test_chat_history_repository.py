import pytest

from app.models.domain import ChatSessionRecord, ChatTurnRecord
from app.repositories.chat_history_repository import InMemoryChatHistoryRepository, get_chat_history_repository


@pytest.mark.asyncio
async def test_in_memory_chat_history_repository_persists_records():
    repository = InMemoryChatHistoryRepository()
    session = ChatSessionRecord(session_id="iris_memory", title="内存会话", updated_at=2.0)
    await repository.save_session(session)
    await repository.save_turn(ChatTurnRecord(turn_id="turn_1", session_id=session.session_id, turn_number=1, query="first"))
    await repository.save_turn(ChatTurnRecord(turn_id="turn_2", session_id=session.session_id, turn_number=2, query="second"))

    assert [item.session_id for item in await repository.list_sessions()] == [session.session_id]
    assert [item.turn_id for item in await repository.list_turns(session.session_id)] == ["turn_2", "turn_1"]


@pytest.mark.asyncio
async def test_default_chat_history_repository_is_in_memory():
    assert isinstance(await get_chat_history_repository(), InMemoryChatHistoryRepository)

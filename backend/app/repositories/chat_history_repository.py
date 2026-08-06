from __future__ import annotations

from typing import Protocol

from app.models.domain import ChatSessionRecord, ChatTurnRecord


class ChatHistoryRepository(Protocol):
    backend_name: str

    async def save_session(self, session: ChatSessionRecord) -> None: ...
    async def save_turn(self, turn: ChatTurnRecord) -> None: ...
    async def get_session(self, session_id: str) -> ChatSessionRecord | None: ...
    async def list_sessions(self, *, limit: int = 50) -> list[ChatSessionRecord]: ...
    async def list_turns(self, session_id: str, *, limit: int = 50) -> list[ChatTurnRecord]: ...


class InMemoryChatHistoryRepository:
    """Process-local chat history for the single-user demo."""

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

    async def list_sessions(self, *, limit: int = 50) -> list[ChatSessionRecord]:
        sessions = list(self._sessions.values())
        sessions.sort(key=lambda session: session.updated_at, reverse=True)
        return sessions[:limit]

    async def list_turns(self, session_id: str, *, limit: int = 50) -> list[ChatTurnRecord]:
        turns = list(self._turns.get(session_id, {}).values())
        turns.sort(key=lambda turn: turn.turn_number, reverse=True)
        return turns[:limit]


_memory_chat_history_repository = InMemoryChatHistoryRepository()


async def get_chat_history_repository() -> ChatHistoryRepository:
    return _memory_chat_history_repository

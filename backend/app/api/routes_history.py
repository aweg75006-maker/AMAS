from fastapi import APIRouter, Query

from app.core.exceptions import AppError
from app.services.chat_history_service import get_chat_history_service


router = APIRouter(prefix="/history", tags=["history"])


@router.get("/sessions")
async def list_history_sessions(
    limit: int = Query(default=50, ge=1, le=200),
):
    service = await get_chat_history_service()
    sessions = await service.list_sessions(limit=limit)
    return {"items": [session.to_dict() for session in sessions]}


@router.get("/sessions/{session_id}")
async def get_history_session(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
):
    service = await get_chat_history_service()
    result = await service.get_session_with_turns(
        session_id=session_id,
        limit=limit,
    )
    if result is None:
        raise AppError(
            code="HISTORY_SESSION_NOT_FOUND",
            message="历史会话不存在",
            status_code=404,
            details={"session_id": session_id},
        )

    session, turns = result
    return {
        "session": session.to_dict(),
        "turns": [turn.to_dict() for turn in turns],
    }

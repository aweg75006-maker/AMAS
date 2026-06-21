from fastapi import APIRouter

from app.api.dependencies import get_assembler
from app.core.exceptions import AppError


router = APIRouter()


@router.post("/sessions")
async def create_session():
    """Create a new session."""
    assembler = await get_assembler()
    await assembler._init()
    session = await assembler.session_mgr.create_session()
    return {
        "session_id": session.session_id,
        "created_at": session.created_at,
        "total_budget": session.total_budget,
        "status": session.status,
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session details, including memory window stats."""
    assembler = await get_assembler()
    info = await assembler.get_session_info(session_id)
    if info is None:
        raise AppError(
            code="SESSION_NOT_FOUND",
            message="会话不存在",
            status_code=404,
            details={"session_id": session_id},
        )
    return info


@router.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str, limit: int = 20):
    """Get layered memory history for a session."""
    assembler = await get_assembler()
    history = await assembler.get_session_history(session_id, limit)
    if history is None:
        raise AppError(
            code="SESSION_NOT_FOUND",
            message="会话不存在",
            status_code=404,
            details={"session_id": session_id},
        )
    return history


@router.get("/sessions/{session_id}/turns/{turn_id}")
async def get_turn_detail(session_id: str, turn_id: str):
    """Get one turn's full details."""
    assembler = await get_assembler()
    detail = await assembler.get_turn_detail(session_id, turn_id)
    if detail is None:
        raise AppError(
            code="TURN_NOT_FOUND",
            message="Turn 不存在",
            status_code=404,
            details={"session_id": session_id, "turn_id": turn_id},
        )
    return detail

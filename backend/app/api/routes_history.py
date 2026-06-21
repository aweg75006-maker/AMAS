from fastapi import APIRouter, Depends, Query

from app.api.context import get_request_context
from app.api.permissions import WRITE_ROLES
from app.core.exceptions import AppError
from app.core.identity import RequestContext
from app.services.chat_history_service import get_chat_history_service


router = APIRouter(prefix="/history", tags=["history"])


@router.get("/sessions")
async def list_history_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    scope: str = Query(default="mine", pattern="^(mine|tenant)$"),
    context: RequestContext = Depends(get_request_context),
):
    service = await get_chat_history_service()
    user_id = None
    if scope == "mine" or context.role not in WRITE_ROLES:
        user_id = context.user_id
    sessions = await service.list_sessions(
        tenant_id=context.tenant_id,
        user_id=user_id,
        limit=limit,
    )
    return {
        "tenant_id": context.tenant_id,
        "scope": "mine" if user_id else "tenant",
        "items": [session.to_dict() for session in sessions],
    }


@router.get("/sessions/{session_id}")
async def get_history_session(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(get_request_context),
):
    service = await get_chat_history_service()
    result = await service.get_session_with_turns(
        tenant_id=context.tenant_id,
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
    if context.role not in WRITE_ROLES and session.user_id != context.user_id:
        raise AppError(
            code="HISTORY_SESSION_NOT_FOUND",
            message="历史会话不存在",
            status_code=404,
            details={"session_id": session_id},
        )

    return {
        "session": session.to_dict(),
        "turns": [turn.to_dict() for turn in turns],
    }

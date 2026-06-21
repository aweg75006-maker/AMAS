from fastapi import APIRouter

from app.api.routes_audit import router as audit_router
from app.api.routes_auth import router as auth_router
from app.api.routes_chat import router as chat_router
from app.api.routes_health import router as health_router
from app.api.routes_knowledge import router as knowledge_router
from app.api.routes_members import router as members_router
from app.api.routes_sessions import router as sessions_router


router = APIRouter()
router.include_router(auth_router)
router.include_router(health_router)
router.include_router(audit_router)
router.include_router(members_router)
router.include_router(knowledge_router)
router.include_router(sessions_router)
router.include_router(chat_router)

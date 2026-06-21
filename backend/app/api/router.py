from fastapi import APIRouter

from app.api.routes_chat import router as chat_router
from app.api.routes_knowledge import router as knowledge_router
from app.api.routes_sessions import router as sessions_router


router = APIRouter()
router.include_router(knowledge_router)
router.include_router(sessions_router)
router.include_router(chat_router)

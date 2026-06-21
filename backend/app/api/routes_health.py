from fastapi import APIRouter

from app.core.config import settings
from app.core.logging import get_logger
from app.repositories.knowledge_base_repository import get_knowledge_base_repository


router = APIRouter()
logger = get_logger("iris.api.health")


@router.get("/health")
async def health_endpoint():
    metadata = {
        "backend": settings.knowledge_metadata_backend,
        "status": "unknown",
    }

    try:
        repository = await get_knowledge_base_repository()
        metadata["backend"] = repository.backend_name
        metadata["status"] = "ok" if await repository.ping() else "unavailable"
    except Exception:
        logger.exception("metadata_health_check_failed")
        metadata["status"] = "unavailable"

    return {
        "status": "ok" if metadata["status"] == "ok" else "degraded",
        "environment": settings.environment,
        "metadata": metadata,
    }

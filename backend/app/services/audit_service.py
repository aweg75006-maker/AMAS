from __future__ import annotations

from uuid import uuid4

from app.core.identity import RequestContext
from app.core.logging import get_logger, get_request_id
from app.models.domain import AuditLog
from app.repositories.audit_repository import AuditRepository, get_audit_repository


logger = get_logger("iris.audit")


class AuditService:
    """Writes durable audit events for protected business operations."""

    def __init__(self, repository: AuditRepository):
        self.repository = repository

    async def record(
        self,
        *,
        action: str,
        tenant_id: str = "",
        actor_user_id: str = "",
        actor_username: str = "",
        target_type: str = "",
        target_id: str = "",
        status: str = "success",
        request_id: str = "",
        details: dict | None = None,
    ) -> AuditLog:
        event = AuditLog(
            audit_id=f"audit_{uuid4().hex[:16]}",
            action=action,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_username=actor_username,
            target_type=target_type,
            target_id=target_id,
            status=status,
            request_id=request_id or get_request_id(),
            details=details or {},
        )
        await self.repository.save_audit_log(event)
        return event

    async def record_for_context(
        self,
        context: RequestContext,
        *,
        action: str,
        target_type: str = "",
        target_id: str = "",
        status: str = "success",
        details: dict | None = None,
    ) -> AuditLog:
        return await self.record(
            action=action,
            tenant_id=context.tenant_id,
            actor_user_id=context.user_id,
            actor_username=context.username,
            target_type=target_type,
            target_id=target_id,
            status=status,
            details=details,
        )

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        action: str | None = None,
        actor_user_id: str | None = None,
    ) -> list[AuditLog]:
        safe_limit = max(1, min(limit, 500))
        return await self.repository.list_audit_logs_for_tenant(
            tenant_id,
            limit=safe_limit,
            action=action.strip() if action else None,
            actor_user_id=actor_user_id.strip() if actor_user_id else None,
        )


async def get_audit_service() -> AuditService:
    repository = await get_audit_repository()
    return AuditService(repository)


async def record_audit_event(**kwargs) -> AuditLog | None:
    try:
        service = await get_audit_service()
        return await service.record(**kwargs)
    except Exception:
        logger.exception("audit_log_write_failed", extra={"audit_action": kwargs.get("action")})
        return None


async def record_audit_event_for_context(
    context: RequestContext,
    **kwargs,
) -> AuditLog | None:
    try:
        service = await get_audit_service()
        return await service.record_for_context(context, **kwargs)
    except Exception:
        logger.exception("audit_log_write_failed", extra={"audit_action": kwargs.get("action")})
        return None

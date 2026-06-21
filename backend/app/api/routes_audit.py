from fastapi import APIRouter, Depends, Query

from app.api.permissions import WRITE_ROLES, require_roles
from app.core.identity import RequestContext
from app.services.audit_service import get_audit_service


router = APIRouter(prefix="/audit-logs", tags=["audit"])
require_audit_reader = require_roles(WRITE_ROLES, allow_header_fallback=False)


@router.get("")
async def list_audit_logs_endpoint(
    limit: int = Query(default=100, ge=1, le=500),
    action: str | None = Query(default=None),
    actor_user_id: str | None = Query(default=None),
    context: RequestContext = Depends(require_audit_reader),
):
    service = await get_audit_service()
    logs = await service.list_for_tenant(
        context.tenant_id,
        limit=limit,
        action=action,
        actor_user_id=actor_user_id,
    )
    return {
        "tenant_id": context.tenant_id,
        "items": [log.to_dict() for log in logs],
    }

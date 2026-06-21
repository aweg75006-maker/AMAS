from fastapi import APIRouter, Depends

from app.api.rate_limits import login_rate_limit
from app.api.schemas import LoginRequest
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.security import create_access_token
from app.models.domain import AuditAction, TenantRole
from app.services.account_service import get_account_service
from app.services.audit_service import record_audit_event


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", dependencies=[Depends(login_rate_limit)])
async def login_endpoint(request: LoginRequest):
    service = await get_account_service()
    await service.ensure_seed_default_user()

    result = await service.authenticate_user(
        username=request.username,
        password=request.password,
    )
    if result is None:
        await record_audit_event(
            action=AuditAction.LOGIN_FAILED.value,
            actor_username=request.username.strip().lower(),
            target_type="user",
            target_id=request.username.strip().lower(),
            status="failed",
            details={"reason": "invalid_credentials"},
        )
        raise AppError(
            code="INVALID_CREDENTIALS",
            message="用户名或密码错误",
            status_code=401,
        )

    user, memberships = result
    active_membership = memberships[0] if memberships else None
    tenant_id = active_membership.tenant_id if active_membership else "default"
    role = active_membership.role if active_membership else TenantRole.VIEWER.value
    access_token = create_access_token(
        user_id=user.user_id,
        username=user.username,
        tenant_id=tenant_id,
        role=role,
    )
    await record_audit_event(
        action=AuditAction.LOGIN_SUCCEEDED.value,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        actor_username=user.username,
        target_type="user",
        target_id=user.user_id,
        status="success",
        details={"role": role},
    )
    return {
        "status": "success",
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_ttl_seconds,
        "user": {
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "status": user.status,
        },
        "active_tenant_id": tenant_id,
        "role": role,
        "memberships": [membership.to_dict() for membership in memberships],
    }

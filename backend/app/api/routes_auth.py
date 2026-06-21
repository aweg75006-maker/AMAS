from fastapi import APIRouter

from app.api.schemas import LoginRequest
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.security import create_access_token
from app.models.domain import TenantRole
from app.services.account_service import get_account_service


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login_endpoint(request: LoginRequest):
    service = await get_account_service()
    await service.ensure_seed_default_user()

    result = await service.authenticate_user(
        username=request.username,
        password=request.password,
    )
    if result is None:
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

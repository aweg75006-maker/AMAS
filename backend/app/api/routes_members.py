from fastapi import APIRouter, Depends

from app.api.permissions import WRITE_ROLES, require_roles
from app.api.schemas import InviteMemberRequest, UpdateMemberRoleRequest
from app.core.identity import RequestContext
from app.models.domain import TenantMembership, UserAccount
from app.services.account_service import get_account_service


router = APIRouter(prefix="/members", tags=["members"])
require_member_admin = require_roles(WRITE_ROLES, allow_header_fallback=False)


def _public_user(user: UserAccount) -> dict:
    return {
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "status": user.status,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "last_login_at": user.last_login_at,
    }


def _member_response(user: UserAccount, membership: TenantMembership) -> dict:
    return {
        "user": _public_user(user),
        "membership": membership.to_dict(),
    }


@router.get("")
async def list_members_endpoint(
    context: RequestContext = Depends(require_member_admin),
):
    service = await get_account_service()
    members = await service.list_members_for_tenant(context.tenant_id)
    return {
        "tenant_id": context.tenant_id,
        "members": [
            _member_response(user, membership)
            for user, membership in members
        ],
    }


@router.post("")
async def invite_member_endpoint(
    request: InviteMemberRequest,
    context: RequestContext = Depends(require_member_admin),
):
    service = await get_account_service()
    user, membership = await service.create_or_attach_member(
        tenant_id=context.tenant_id,
        username=request.username,
        email=request.email,
        display_name=request.display_name,
        role=request.role,
    )
    return {
        "status": "success",
        "tenant_id": context.tenant_id,
        "member": _member_response(user, membership),
    }


@router.patch("/{user_id}/role")
async def update_member_role_endpoint(
    user_id: str,
    request: UpdateMemberRoleRequest,
    context: RequestContext = Depends(require_member_admin),
):
    service = await get_account_service()
    membership = await service.change_member_role(
        tenant_id=context.tenant_id,
        user_id=user_id,
        role=request.role,
    )
    return {
        "status": "success",
        "tenant_id": context.tenant_id,
        "membership": membership.to_dict(),
    }


@router.post("/{user_id}/disable")
async def disable_member_endpoint(
    user_id: str,
    context: RequestContext = Depends(require_member_admin),
):
    service = await get_account_service()
    membership = await service.disable_member(
        tenant_id=context.tenant_id,
        user_id=user_id,
    )
    return {
        "status": "success",
        "tenant_id": context.tenant_id,
        "membership": membership.to_dict(),
    }

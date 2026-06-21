from collections.abc import Iterable

from fastapi import Depends

from app.api.context import get_request_context
from app.core.exceptions import AppError
from app.core.identity import RequestContext
from app.models.domain import TenantRole


WRITE_ROLES = {TenantRole.OWNER.value, TenantRole.ADMIN.value}
READ_ROLES = {
    TenantRole.OWNER.value,
    TenantRole.ADMIN.value,
    TenantRole.MEMBER.value,
    TenantRole.VIEWER.value,
}


def require_roles(
    allowed_roles: Iterable[str],
    *,
    allow_header_fallback: bool = True,
):
    allowed = set(allowed_roles)

    async def dependency(
        context: RequestContext = Depends(get_request_context),
    ) -> RequestContext:
        if context.auth_source == "headers" and allow_header_fallback:
            return context
        if context.role in allowed:
            return context
        raise AppError(
            code="FORBIDDEN",
            message="当前账号没有权限执行该操作",
            status_code=403,
            details={"required_roles": sorted(allowed), "role": context.role or None},
        )

    return dependency


require_write_access = require_roles(WRITE_ROLES)
require_read_access = require_roles(READ_ROLES)

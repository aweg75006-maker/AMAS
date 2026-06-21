from fastapi import Header

from app.core.identity import (
    DEFAULT_TENANT_ID,
    DEFAULT_USER_ID,
    RequestContext,
    clean_context_id,
)
from app.core.security import decode_access_token


async def get_request_context(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
) -> RequestContext:
    authorization = authorization if isinstance(authorization, str) else None
    if authorization and authorization.lower().startswith("bearer "):
        payload = decode_access_token(authorization.split(" ", 1)[1].strip())
        return RequestContext(
            tenant_id=clean_context_id(payload.get("tenant_id"), DEFAULT_TENANT_ID),
            user_id=clean_context_id(payload.get("sub"), DEFAULT_USER_ID),
            username=clean_context_id(payload.get("username"), ""),
            role=clean_context_id(payload.get("role"), ""),
            auth_source="jwt",
        )

    return RequestContext(
        tenant_id=clean_context_id(x_tenant_id, DEFAULT_TENANT_ID),
        user_id=clean_context_id(x_user_id, DEFAULT_USER_ID),
        auth_source="headers",
    )

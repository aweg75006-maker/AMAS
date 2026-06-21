from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request

from app.api.context import get_request_context
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.identity import RequestContext, clean_context_id
from app.models.domain import AuditAction
from app.services.audit_service import record_audit_event
from app.services.rate_limit_service import RateLimitRule, get_rate_limiter


LOGIN_RULE = RateLimitRule(
    name="login",
    capacity=settings.rate_limit_login_capacity,
    refill_per_second=settings.rate_limit_login_refill_per_second,
)
CHAT_RULE = RateLimitRule(
    name="chat",
    capacity=settings.rate_limit_chat_capacity,
    refill_per_second=settings.rate_limit_chat_refill_per_second,
)
UPLOAD_RULE = RateLimitRule(
    name="upload",
    capacity=settings.rate_limit_upload_capacity,
    refill_per_second=settings.rate_limit_upload_refill_per_second,
)
DEFAULT_RULE = RateLimitRule(
    name="default",
    capacity=settings.rate_limit_default_capacity,
    refill_per_second=settings.rate_limit_default_refill_per_second,
)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return clean_context_id(forwarded.split(",", 1)[0], "unknown_ip")
    if request.client and request.client.host:
        return clean_context_id(request.client.host, "unknown_ip")
    return "unknown_ip"


def identity_key(context: RequestContext, request: Request) -> str:
    tenant_id = clean_context_id(context.tenant_id, "default")
    user_id = clean_context_id(context.user_id, "anonymous")
    if context.auth_source == "jwt":
        return f"tenant:{tenant_id}:user:{user_id}"
    return f"tenant:{tenant_id}:ip:{client_ip(request)}"


def rate_limit_dependency(
    rule: RateLimitRule,
    *,
    key_builder: Callable[[Request, RequestContext], str],
):
    async def dependency(
        request: Request,
        context: RequestContext = Depends(get_request_context),
    ) -> None:
        limiter = await get_rate_limiter()
        key = f"rate_limit:{rule.name}:{key_builder(request, context)}"
        result = await limiter.check(key=key, rule=rule)
        if result.allowed:
            return

        await record_audit_event(
            action=AuditAction.RATE_LIMIT_EXCEEDED.value,
            tenant_id=context.tenant_id,
            actor_user_id=context.user_id,
            actor_username=context.username,
            target_type="rate_limit",
            target_id=rule.name,
            status="blocked",
            details={
                "rule": rule.name,
                "key": key,
                "retry_after_seconds": result.retry_after_seconds,
                "backend": result.backend,
                "path": request.url.path,
            },
        )
        raise AppError(
            code="RATE_LIMIT_EXCEEDED",
            message="请求过于频繁，请稍后再试",
            status_code=429,
            details={
                "rule": rule.name,
                "retry_after_seconds": result.retry_after_seconds,
            },
        )

    return dependency


login_rate_limit = rate_limit_dependency(
    LOGIN_RULE,
    key_builder=lambda request, _context: f"ip:{client_ip(request)}",
)
chat_rate_limit = rate_limit_dependency(
    CHAT_RULE,
    key_builder=lambda request, context: identity_key(context, request),
)
upload_rate_limit = rate_limit_dependency(
    UPLOAD_RULE,
    key_builder=lambda request, context: identity_key(context, request),
)
default_rate_limit = rate_limit_dependency(
    DEFAULT_RULE,
    key_builder=lambda request, context: identity_key(context, request),
)

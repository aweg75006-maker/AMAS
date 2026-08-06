from __future__ import annotations

from collections.abc import Callable

from fastapi import Request

from app.core.config import settings
from app.core.exceptions import AppError
from app.services.rate_limit_service import RateLimitRule, get_rate_limiter


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
        return forwarded.split(",", 1)[0].strip() or "unknown_ip"
    if request.client and request.client.host:
        return request.client.host
    return "unknown_ip"


def rate_limit_dependency(
    rule: RateLimitRule,
    *,
    key_builder: Callable[[Request], str],
):
    async def dependency(request: Request) -> None:
        limiter = await get_rate_limiter()
        key = f"rate_limit:{rule.name}:{key_builder(request)}"
        result = await limiter.check(key=key, rule=rule)
        if result.allowed:
            return

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


chat_rate_limit = rate_limit_dependency(
    CHAT_RULE,
    key_builder=lambda request: f"ip:{client_ip(request)}",
)
upload_rate_limit = rate_limit_dependency(
    UPLOAD_RULE,
    key_builder=lambda request: f"ip:{client_ip(request)}",
)
default_rate_limit = rate_limit_dependency(
    DEFAULT_RULE,
    key_builder=lambda request: f"ip:{client_ip(request)}",
)

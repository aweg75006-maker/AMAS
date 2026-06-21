import pytest

from app.services.rate_limit_service import RateLimitRule, TokenBucketRateLimiter
from app.utils.redis_client import RedisClient


@pytest.mark.asyncio
async def test_token_bucket_allows_capacity_then_blocks(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    redis = RedisClient(url="redis://localhost:1/0")
    limiter = TokenBucketRateLimiter(redis)
    rule = RateLimitRule(name="test", capacity=2, refill_per_second=1 / 60)

    first = await limiter.check(key="rl:test", rule=rule, now=1000)
    second = await limiter.check(key="rl:test", rule=rule, now=1001)
    third = await limiter.check(key="rl:test", rule=rule, now=1002)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.retry_after_seconds > 0
    assert third.backend == "memory"


@pytest.mark.asyncio
async def test_token_bucket_refills_over_time(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    redis = RedisClient(url="redis://localhost:1/0")
    limiter = TokenBucketRateLimiter(redis)
    rule = RateLimitRule(name="test", capacity=1, refill_per_second=1)

    first = await limiter.check(key="rl:refill", rule=rule, now=1000)
    second = await limiter.check(key="rl:refill", rule=rule, now=1000.1)
    third = await limiter.check(key="rl:refill", rule=rule, now=1001.1)

    assert first.allowed is True
    assert second.allowed is False
    assert third.allowed is True

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.core.config import settings
from app.core.logging import get_logger
from app.utils.redis_client import RedisClient


logger = get_logger("iris.rate_limit")

TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local bucket = redis.call("HMGET", key, "tokens", "updated_at")
local tokens = tonumber(bucket[1])
local updated_at = tonumber(bucket[2])

if tokens == nil then
  tokens = capacity
  updated_at = now
end

local elapsed = math.max(0, now - updated_at)
tokens = math.min(capacity, tokens + (elapsed * refill_rate))

local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end

redis.call("HMSET", key, "tokens", tostring(tokens), "updated_at", tostring(now))
redis.call("EXPIRE", key, ttl)

local retry_after = 0
if allowed == 0 and refill_rate > 0 then
  retry_after = math.ceil((cost - tokens) / refill_rate)
end

return {allowed, tokens, retry_after}
"""


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    capacity: int
    refill_per_second: float
    cost: int = 1


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: float
    retry_after_seconds: int
    key: str
    rule: RateLimitRule
    backend: str


@dataclass
class MemoryBucket:
    tokens: float
    updated_at: float


class TokenBucketRateLimiter:
    """Token bucket limiter with Redis atomic path and in-memory fallback."""

    def __init__(self, redis: RedisClient | None = None):
        self.redis = redis or RedisClient()
        self._memory_buckets: dict[str, MemoryBucket] = {}
        self._lock = asyncio.Lock()

    async def check(
        self,
        *,
        key: str,
        rule: RateLimitRule,
        now: float | None = None,
    ) -> RateLimitResult:
        if not settings.rate_limit_enabled:
            return RateLimitResult(
                allowed=True,
                remaining=float(rule.capacity),
                retry_after_seconds=0,
                key=key,
                rule=rule,
                backend="disabled",
            )

        await self._ensure_connected()
        now = now or time.time()
        if self.redis._client is not None:
            try:
                return await self._check_redis(key=key, rule=rule, now=now)
            except Exception:
                logger.exception("rate_limit_redis_failed", extra={"rate_limit_key": key})

        return await self._check_memory(key=key, rule=rule, now=now)

    async def _ensure_connected(self) -> None:
        if not self.redis.connected:
            await self.redis.connect()

    async def _check_redis(
        self,
        *,
        key: str,
        rule: RateLimitRule,
        now: float,
    ) -> RateLimitResult:
        ttl = self._ttl_for(rule)
        result = await self.redis._client.eval(
            TOKEN_BUCKET_LUA,
            1,
            key,
            rule.capacity,
            rule.refill_per_second,
            now,
            rule.cost,
            ttl,
        )
        allowed = bool(int(float(result[0])))
        remaining = float(result[1])
        retry_after = int(float(result[2]))
        return RateLimitResult(
            allowed=allowed,
            remaining=max(0.0, remaining),
            retry_after_seconds=max(0, retry_after),
            key=key,
            rule=rule,
            backend="redis",
        )

    async def _check_memory(
        self,
        *,
        key: str,
        rule: RateLimitRule,
        now: float,
    ) -> RateLimitResult:
        async with self._lock:
            bucket = self._memory_buckets.get(key)
            if bucket is None:
                bucket = MemoryBucket(tokens=float(rule.capacity), updated_at=now)

            elapsed = max(0.0, now - bucket.updated_at)
            tokens = min(
                float(rule.capacity),
                bucket.tokens + elapsed * rule.refill_per_second,
            )
            allowed = tokens >= rule.cost
            if allowed:
                tokens -= rule.cost
            bucket.tokens = tokens
            bucket.updated_at = now
            self._memory_buckets[key] = bucket

        retry_after = 0
        if not allowed and rule.refill_per_second > 0:
            retry_after = int((rule.cost - tokens) / rule.refill_per_second) + 1
        return RateLimitResult(
            allowed=allowed,
            remaining=max(0.0, tokens),
            retry_after_seconds=max(0, retry_after),
            key=key,
            rule=rule,
            backend="memory",
        )

    def _ttl_for(self, rule: RateLimitRule) -> int:
        if rule.refill_per_second <= 0:
            return 3600
        return max(60, int((rule.capacity / rule.refill_per_second) * 2))


_rate_limiters: dict[int, TokenBucketRateLimiter] = {}


async def get_rate_limiter() -> TokenBucketRateLimiter:
    loop_id = id(asyncio.get_running_loop())
    limiter = _rate_limiters.get(loop_id)
    if limiter is None:
        limiter = TokenBucketRateLimiter()
        _rate_limiters[loop_id] = limiter
    return limiter

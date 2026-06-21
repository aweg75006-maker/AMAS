from app.services.rate_limit_service import TokenBucketRateLimiter
from app.utils.redis_client import RedisClient


def test_login_rate_limit_returns_429_and_audit_event(client, monkeypatch):
    import app.api.rate_limits as rate_limits
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    redis = RedisClient(url="redis://localhost:1/0")
    limiter = TokenBucketRateLimiter(redis)

    async def fake_get_rate_limiter():
        return limiter

    monkeypatch.setattr(rate_limits, "get_rate_limiter", fake_get_rate_limiter)

    responses = [
        client.post(
            "/api/auth/login",
            json={"username": "missing-user", "password": "wrong-password"},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        for _ in range(6)
    ]

    assert [response.status_code for response in responses[:5]] == [401] * 5
    assert responses[-1].status_code == 429
    body = responses[-1].json()
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["error"]["details"]["retry_after_seconds"] > 0

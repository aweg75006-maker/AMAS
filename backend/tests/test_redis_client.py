import pytest

from app.utils.redis_client import RedisClient
from app.utils.session_manager import SessionManager


@pytest.mark.asyncio
async def test_redis_client_falls_back_when_unavailable():
    client = RedisClient(url="redis://localhost:1/0")

    await client.connect()
    try:
        assert client.connected is True
        assert client.is_fallback is True
        assert await client.ping() is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_redis_client_uses_real_redis_when_available():
    client = RedisClient()

    await client.connect()
    try:
        if client.is_fallback:
            pytest.skip("Redis is unavailable in this environment.")

        assert client.connected is True
        assert client.is_fallback is False
        assert await client.ping() is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_session_manager_persists_session_to_redis_or_fallback():
    client = RedisClient()
    await client.connect()
    try:
        manager = SessionManager(client)
        session = await manager.create_session(total_budget=42_000)

        exists = await client.session_exists(session.session_id)
        meta = await client.get_session_meta(session.session_id)

        assert exists is True
        assert meta["session_id"] == session.session_id
        assert meta["total_budget"] == "42000"
    finally:
        await client.close()

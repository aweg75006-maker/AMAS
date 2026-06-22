"""
Redis 客户端封装：异步连接池 + 健康检查 + 优雅降级。

当 Redis 不可用时（本地开发/未安装 Redis Server），
自动降级到内存字典存储，保证系统正常运行。

Key Schema（遵循架构设计文档 6.2 节）：
    session:{sid}:meta          → Hash
    session:{sid}:turn_index    → List
    session:{sid}:turn:{tid}    → Hash
    session:{sid}:turn:{tid}:full  → String
    session:{sid}:budget        → Hash
    checkpoint:{thread_id}:{ns} → String
"""

import json
import asyncio
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import logging
import fnmatch
from app.core.config import settings

logger = logging.getLogger("iris.redis")

# ─── 配置 ───
REDIS_URL = settings.redis_url
REDIS_ENABLED = settings.redis_enabled
SESSION_TTL = settings.redis_session_ttl  # 7 天
TURN_FULL_TTL = settings.redis_turn_full_ttl  # 3 天
CHECKPOINT_TTL = settings.redis_checkpoint_ttl  # 7 天


class RedisNotAvailableError(Exception):
    """Redis 不可用时抛出（内部使用，调用方不应感知）。"""
    pass


# ─── 内存降级存储 ───
@dataclass
class InMemoryStore:
    """当 Redis 不可用时的内存字典降级方案。"""
    data: Dict[str, Any] = field(default_factory=dict)
    expirations: Dict[str, float] = field(default_factory=dict)

    async def get(self, key: str) -> Optional[Any]:
        self._cleanup()
        return self.data.get(key)

    async def set(self, key: str, value: Any, ex: Optional[int] = None):
        import time
        self.data[key] = value
        if ex:
            self.expirations[key] = time.time() + ex

    async def delete(self, key: str):
        self.data.pop(key, None)
        self.expirations.pop(key, None)

    async def hgetall(self, key: str) -> Dict[str, str]:
        self._cleanup()
        val = self.data.get(key, {})
        if isinstance(val, dict):
            return {k: str(v) for k, v in val.items()}
        return {}

    async def hset(self, key: str, mapping: Dict[str, Any]):
        self.data[key] = {**self.data.get(key, {}), **mapping}

    async def hget(self, key: str, field: str) -> Optional[str]:
        self._cleanup()
        val = self.data.get(key, {})
        if isinstance(val, dict):
            v = val.get(field)
            return str(v) if v is not None else None
        return None

    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        self._cleanup()
        val = self.data.get(key, [])
        if isinstance(val, list):
            return [str(v) for v in val[start:end+1 if end >= 0 else None]]
        return []

    async def rpush(self, key: str, *values: str) -> int:
        if key not in self.data or not isinstance(self.data[key], list):
            self.data[key] = []
        self.data[key].extend(values)
        return len(self.data[key])

    async def llen(self, key: str) -> int:
        self._cleanup()
        val = self.data.get(key, [])
        return len(val) if isinstance(val, list) else 0

    async def exists(self, key: str) -> bool:
        self._cleanup()
        return key in self.data

    async def keys(self, pattern: str) -> List[str]:
        self._cleanup()
        return [key for key in self.data.keys() if fnmatch.fnmatch(key, pattern)]

    async def expire(self, key: str, ttl: int):
        import time
        if key in self.data:
            self.expirations[key] = time.time() + ttl

    def _cleanup(self):
        """清理过期键。"""
        import time
        now = time.time()
        expired = [k for k, t in list(self.expirations.items()) if t < now]
        for k in expired:
            self.data.pop(k, None)
            self.expirations.pop(k, None)

    async def ping(self) -> bool:
        return True


class RedisClient:
    """
    异步 Redis 客户端封装。

    用法:
        redis = RedisClient()
        await redis.connect()

        # 会话操作
        await redis.hset("session:abc:meta", {"created_at": "..."})
        meta = await redis.hgetall("session:abc:meta")

        # 降级检查
        if redis.is_fallback:
            print("运行在内存模式，重启后数据丢失")

        await redis.close()
    """

    def __init__(self, url: Optional[str] = None):
        self.url = url or REDIS_URL
        self._client = None
        self._fallback: Optional[InMemoryStore] = None
        self._connected = False

    # ─── 生命周期 ───

    async def connect(self) -> None:
        """建立 Redis 连接。如果失败，降级到内存存储。"""
        if not REDIS_ENABLED:
            logger.info("Redis 已禁用（REDIS_ENABLED=false），使用内存降级存储")
            self._fallback = InMemoryStore()
            self._connected = True
            return

        try:
            import redis.asyncio as aioredis
            self._client = aioredis.from_url(
                self.url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
            )
            # 连接测试
            await asyncio.wait_for(self._client.ping(), timeout=2)
            self._connected = True
            logger.info(f"Redis 连接成功: {self.url}")
        except Exception as e:
            self._client = None
            logger.warning(
                f"Redis 不可用 ({e})，降级到内存存储。"
                f"提示: 启动 Redis Server 或在 .env 中设置 REDIS_ENABLED=false 来消除此警告。"
            )
            self._fallback = InMemoryStore()
            self._connected = True

    async def close(self) -> None:
        """关闭连接。"""
        if self._client:
            try:
                if hasattr(self._client, "aclose"):
                    await self._client.aclose()
                else:
                    await self._client.close()
            except Exception:
                pass
            self._client = None
        self._fallback = None
        self._connected = False

    @property
    def is_fallback(self) -> bool:
        """当前是否运行在内存降级模式。"""
        return self._fallback is not None and self._client is None

    @property
    def connected(self) -> bool:
        return self._connected

    # ─── 基础操作 ───

    async def ping(self) -> bool:
        """健康检查。"""
        if self._client:
            try:
                return await self._client.ping()
            except Exception:
                return False
        return bool(self._fallback)

    # ─── String 操作 ───

    async def get(self, key: str) -> Optional[str]:
        if self._client:
            try:
                return await self._client.get(key)
            except Exception:
                pass
        if self._fallback:
            return await self._fallback.get(key)
        return None

    async def set(self, key: str, value: str, ex: Optional[int] = None):
        if self._client:
            try:
                await self._client.set(key, value, ex=ex)
                return
            except Exception:
                pass
        if self._fallback:
            await self._fallback.set(key, value, ex=ex)

    async def delete(self, key: str):
        if self._client:
            try:
                await self._client.delete(key)
                return
            except Exception:
                pass
        if self._fallback:
            await self._fallback.delete(key)

    # ─── Hash 操作 ───

    async def hgetall(self, key: str) -> Dict[str, str]:
        if self._client:
            try:
                return await self._client.hgetall(key)
            except Exception:
                pass
        if self._fallback:
            return await self._fallback.hgetall(key)
        return {}

    async def hset(self, key: str, mapping: Dict[str, Any]):
        str_mapping = {k: str(v) if v is not None else "" for k, v in mapping.items()}
        if self._client:
            try:
                await self._client.hset(key, mapping=str_mapping)
                return
            except Exception:
                pass
        if self._fallback:
            await self._fallback.hset(key, str_mapping)

    async def hget(self, key: str, field: str) -> Optional[str]:
        if self._client:
            try:
                return await self._client.hget(key, field)
            except Exception:
                pass
        if self._fallback:
            return await self._fallback.hget(key, field)
        return None

    # ─── List 操作 ───

    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        if self._client:
            try:
                return await self._client.lrange(key, start, end)
            except Exception:
                pass
        if self._fallback:
            return await self._fallback.lrange(key, start, end)
        return []

    async def rpush(self, key: str, *values: str) -> int:
        if self._client:
            try:
                return await self._client.rpush(key, *values)
            except Exception:
                pass
        if self._fallback:
            return await self._fallback.rpush(key, *values)
        return 0

    async def llen(self, key: str) -> int:
        if self._client:
            try:
                return await self._client.llen(key)
            except Exception:
                pass
        if self._fallback:
            return await self._fallback.llen(key)
        return 0

    # ─── 键管理 ───

    async def exists(self, key: str) -> bool:
        if self._client:
            try:
                return bool(await self._client.exists(key))
            except Exception:
                pass
        if self._fallback:
            return await self._fallback.exists(key)
        return False

    async def keys(self, pattern: str) -> List[str]:
        if self._client:
            try:
                return [key async for key in self._client.scan_iter(match=pattern)]
            except Exception:
                pass
        if self._fallback:
            return await self._fallback.keys(pattern)
        return []

    async def expire(self, key: str, ttl: int):
        if self._client:
            try:
                await self._client.expire(key, ttl)
                return
            except Exception:
                pass
        if self._fallback:
            await self._fallback.expire(key, ttl)

    # ─── 高层 API：会话 ───

    async def create_session(self, session_id: str, meta: Dict[str, Any]) -> None:
        """创建新会话。"""
        await self.hset(f"session:{session_id}:meta", meta)
        await self.expire(f"session:{session_id}:meta", SESSION_TTL)

    async def get_session_meta(self, session_id: str) -> Dict[str, str]:
        """读取会话元数据。"""
        return await self.hgetall(f"session:{session_id}:meta")

    async def update_session_meta(self, session_id: str, updates: Dict[str, Any]) -> None:
        """更新会话元数据。"""
        await self.hset(f"session:{session_id}:meta", updates)

    async def session_exists(self, session_id: str) -> bool:
        """检查会话是否存在。"""
        return await self.exists(f"session:{session_id}:meta")

    async def add_turn(self, session_id: str, turn_id: str) -> int:
        """向会话添加一个 Turn，返回当前 Turn 总数。"""
        await self.rpush(f"session:{session_id}:turn_index", turn_id)
        return await self.llen(f"session:{session_id}:turn_index")

    async def get_turn_ids(self, session_id: str) -> List[str]:
        """获取会话的所有 Turn ID（按时间排序）。"""
        return await self.lrange(f"session:{session_id}:turn_index", 0, -1)

    async def save_turn(self, session_id: str, turn_id: str, turn_data: Dict[str, Any]) -> None:
        """保存 Turn 摘要数据。"""
        await self.hset(f"session:{session_id}:turn:{turn_id}", turn_data)
        await self.expire(f"session:{session_id}:turn:{turn_id}", SESSION_TTL)

    async def save_turn_full(self, session_id: str, turn_id: str, full_data: str) -> None:
        """保存 Turn 完整数据（大字段，冷数据）。"""
        await self.set(
            f"session:{session_id}:turn:{turn_id}:full",
            full_data,
            ex=TURN_FULL_TTL,
        )

    async def get_turn(self, session_id: str, turn_id: str) -> Dict[str, str]:
        """读取 Turn 摘要数据。"""
        return await self.hgetall(f"session:{session_id}:turn:{turn_id}")

    async def get_turn_full(self, session_id: str, turn_id: str) -> Optional[str]:
        """读取 Turn 完整数据。"""
        return await self.get(f"session:{session_id}:turn:{turn_id}:full")

    # ─── 高层 API：预算 ───

    async def save_budget(self, session_id: str, budget_data: Dict[str, Any]) -> None:
        """保存 Token 预算账簿。"""
        await self.hset(f"session:{session_id}:budget", budget_data)
        await self.expire(f"session:{session_id}:budget", SESSION_TTL)

    async def get_budget(self, session_id: str) -> Dict[str, str]:
        """读取 Token 预算账簿。"""
        return await self.hgetall(f"session:{session_id}:budget")

    # ─── 高层 API：Checkpoint ───

    async def save_checkpoint(self, thread_id: str, namespace: str, data: str) -> None:
        """保存 workflow checkpoint。"""
        key = f"checkpoint:{thread_id}:{namespace}"
        await self.set(key, data, ex=CHECKPOINT_TTL)

    async def get_checkpoint(self, thread_id: str, namespace: str) -> Optional[str]:
        """读取 workflow checkpoint。"""
        return await self.get(f"checkpoint:{thread_id}:{namespace}")


# ─── 全局单例 ───

_redis_client: Optional[RedisClient] = None
_lock = asyncio.Lock()


async def get_redis() -> RedisClient:
    """获取全局 RedisClient 单例（懒连接）。"""
    global _redis_client
    if _redis_client is not None and _redis_client.connected:
        return _redis_client

    async with _lock:
        if _redis_client is not None and _redis_client.connected:
            return _redis_client
        _redis_client = RedisClient()
        await _redis_client.connect()
        return _redis_client


async def close_redis():
    """关闭全局 Redis 连接。"""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None

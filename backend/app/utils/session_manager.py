"""
会话管理器：生命周期管理 + 跨轮状态追踪。

职责：
1. 服务端生成 session_id（替代前端 UUID）
2. 会话 CRUD（创建、加载、更新、归档）
3. Turn 计数与索引维护
4. TTL 自动续期
5. 通过 RedisClient 持久化（或内存降级）
"""

import uuid
import time
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from app.utils.redis_client import get_redis, RedisClient


# ─── 数据模型 ───

@dataclass
class TurnRecord:
    """Turn 的完整记录（Episodic Memory 使用）。"""
    turn_id: str
    turn_number: int
    query: str
    plan: List[str] = field(default_factory=list)
    search_results: List[str] = field(default_factory=list)
    final_report: str = ""
    critique: str = ""
    review_status: str = ""
    search_mode: str = "hybrid"
    token_usage: Dict[str, int] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "turn_number": str(self.turn_number),
            "query": self.query,
            "plan": json.dumps(self.plan, ensure_ascii=False),
            "search_results": json.dumps(self.search_results, ensure_ascii=False),
            "final_report": self.final_report,
            "critique": self.critique,
            "review_status": self.review_status,
            "search_mode": self.search_mode,
            "token_usage": json.dumps(self.token_usage),
            "timestamp": str(self.timestamp),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "TurnRecord":
        return cls(
            turn_id=d.get("turn_id", ""),
            turn_number=int(d.get("turn_number", 0)),
            query=d.get("query", ""),
            plan=json.loads(d.get("plan", "[]")),
            search_results=json.loads(d.get("search_results", "[]")),
            final_report=d.get("final_report", ""),
            critique=d.get("critique", ""),
            review_status=d.get("review_status", ""),
            search_mode=d.get("search_mode", "hybrid"),
            token_usage=json.loads(d.get("token_usage", "{}")),
            timestamp=float(d.get("timestamp", 0)),
        )


@dataclass
class SessionMeta:
    """会话元数据。"""
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    turns_count: int = 0
    total_budget: int = 128_000
    total_estimated_tokens: int = 0
    total_actual_tokens: int = 0
    compression_savings: int = 0
    status: str = "active"  # active / archived / expired

    def to_dict(self) -> Dict[str, str]:
        return {
            "session_id": self.session_id,
            "created_at": str(self.created_at),
            "last_active": str(self.last_active),
            "turns_count": str(self.turns_count),
            "total_budget": str(self.total_budget),
            "total_estimated_tokens": str(self.total_estimated_tokens),
            "total_actual_tokens": str(self.total_actual_tokens),
            "compression_savings": str(self.compression_savings),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "SessionMeta":
        return cls(
            session_id=d.get("session_id", ""),
            created_at=float(d.get("created_at", 0)),
            last_active=float(d.get("last_active", 0)),
            turns_count=int(d.get("turns_count", 0)),
            total_budget=int(d.get("total_budget", 128_000)),
            total_estimated_tokens=int(d.get("total_estimated_tokens", 0)),
            total_actual_tokens=int(d.get("total_actual_tokens", 0)),
            compression_savings=int(d.get("compression_savings", 0)),
            status=d.get("status", "active"),
        )


# ─── 会话管理器 ───

class SessionManager:
    """
    会话生命周期管理器。

    用法:
        mgr = SessionManager(redis_client)

        # 创建新会话
        session = await mgr.create_session()
        sid = session.session_id

        # 加载已有会话
        session = await mgr.load_session(sid)

        # 记录新 Turn
        mgr.record_turn(sid, turn_record)

        # 列出活跃会话
        sessions = await mgr.list_sessions()
    """

    def __init__(self, redis: Optional[RedisClient] = None):
        self._redis: Optional[RedisClient] = redis
        # 内存缓存：减少 Redis 往返
        self._cache: Dict[str, SessionMeta] = {}

    async def _get_redis(self) -> RedisClient:
        if self._redis is not None:
            return self._redis
        return await get_redis()

    # ─── 会话 CRUD ───

    async def create_session(
        self, total_budget: int = 128_000
    ) -> SessionMeta:
        """创建新会话。返回 SessionMeta。"""
        session_id = self._generate_session_id()
        meta = SessionMeta(
            session_id=session_id,
            total_budget=total_budget,
        )
        self._cache[session_id] = meta

        redis = await self._get_redis()
        await redis.create_session(session_id, meta.to_dict())

        return meta

    async def load_session(self, session_id: str) -> Optional[SessionMeta]:
        """加载已有会话。不存在返回 None。"""
        # 先查缓存
        if session_id in self._cache:
            return self._cache[session_id]

        redis = await self._get_redis()
        if not await redis.session_exists(session_id):
            return None

        data = await redis.get_session_meta(session_id)
        if not data:
            return None

        meta = SessionMeta.from_dict(data)
        self._cache[session_id] = meta
        return meta

    async def get_or_create_session(
        self, session_id: Optional[str] = None
    ) -> SessionMeta:
        """获取已有会话，或创建新会话。"""
        if session_id:
            meta = await self.load_session(session_id)
            if meta:
                return meta
        return await self.create_session()

    async def update_session(
        self, session_id: str, updates: Dict[str, Any]
    ) -> None:
        """更新会话元数据。"""
        meta = await self.load_session(session_id)
        if meta is None:
            return

        # 更新本地字段
        for key, value in updates.items():
            if hasattr(meta, key):
                setattr(meta, key, value)

        meta.last_active = time.time()
        self._cache[session_id] = meta

        # 持久化
        redis = await self._get_redis()
        await redis.update_session_meta(session_id, meta.to_dict())

    async def touch_session(self, session_id: str) -> None:
        """续期会话（更新 last_active）。"""
        await self.update_session(session_id, {"last_active": time.time()})

    async def list_sessions(
        self, status: str = "active", limit: int = 20
    ) -> List[SessionMeta]:
        """
        列出会话。

        Phase 1：仅从缓存返回（内存降级模式下无法全量列出）。
        Phase 2：通过 Redis SCAN 实现完整列表。
        """
        # 从缓存过滤
        sessions = [
            m for m in self._cache.values()
            if m.status == status
        ]
        sessions.sort(key=lambda m: m.last_active, reverse=True)
        return sessions[:limit]

    # ─── Turn 管理 ───

    async def record_turn(
        self, session_id: str, turn_record: TurnRecord
    ) -> int:
        """
        向会话记录一个新 Turn。
        返回该 Turn 在会话中的序号。
        """
        redis = await self._get_redis()
        turn_number = await redis.add_turn(session_id, turn_record.turn_id)

        # 保存 Turn 摘要到 Redis
        await redis.save_turn(session_id, turn_record.turn_id, turn_record.to_dict())

        # 保存完整数据（大字段）
        full_data = json.dumps({
            "query": turn_record.query,
            "plan": turn_record.plan,
            "search_results": turn_record.search_results,
            "final_report": turn_record.final_report,
        }, ensure_ascii=False)
        await redis.save_turn_full(session_id, turn_record.turn_id, full_data)

        # 更新会话计数
        await self.update_session(session_id, {"turns_count": turn_number})

        return turn_number

    async def get_turn(
        self, session_id: str, turn_id: str
    ) -> Optional[TurnRecord]:
        """读取指定 Turn 的记录。"""
        redis = await self._get_redis()
        data = await redis.get_turn(session_id, turn_id)
        if not data:
            return None
        return TurnRecord.from_dict(data)

    async def get_recent_turns(
        self, session_id: str, k: int = 3
    ) -> List[TurnRecord]:
        """获取最近 K 个 Turn 的完整记录（Episodic Memory）。"""
        redis = await self._get_redis()
        turn_ids = await redis.get_turn_ids(session_id)

        # 取最后 K 个
        recent_ids = turn_ids[-k:] if len(turn_ids) > k else turn_ids

        turns = []
        for tid in recent_ids:
            record = await self.get_turn(session_id, tid)
            if record:
                turns.append(record)

        return turns

    async def get_turn_count(self, session_id: str) -> int:
        """获取会话的 Turn 总数。"""
        meta = await self.load_session(session_id)
        if meta:
            return meta.turns_count
        return 0

    # ─── 预算集成 ───

    async def save_budget_snapshot(
        self, session_id: str, budget_data: Dict[str, Any]
    ) -> None:
        """保存预算快照到 Redis。"""
        redis = await self._get_redis()
        await redis.save_budget(session_id, budget_data)

    async def get_budget_snapshot(
        self, session_id: str
    ) -> Dict[str, str]:
        """从 Redis 读取预算快照。"""
        redis = await self._get_redis()
        return await redis.get_budget(session_id)

    # ─── 工具方法 ───

    @staticmethod
    def _generate_session_id() -> str:
        """生成服务端会话 ID：iris_ + 短 UUID。"""
        short_uuid = uuid.uuid4().hex[:12]
        return f"iris_{short_uuid}"

    @staticmethod
    def generate_turn_id() -> str:
        """生成 Turn ID。"""
        return f"turn_{uuid.uuid4().hex[:8]}"

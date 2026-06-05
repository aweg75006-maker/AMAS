"""
上下文装配器：会话层与节点层之间的桥梁。

Phase 1 职责：
1. 请求入口：加载/创建 Session + BudgetLedger
2. 图执行前：注入 session_id / turn_id / budget_state 到 AgentState
3. 图执行后：记录 Turn、更新 Session、持久化

用法 (在 routes.py 中):
    assembler = ContextAssembler()
    state, ledger = await assembler.prepare(query, search_mode, session_id)

    # 运行 LangGraph...
    async for event in app.astream(state, config):
        ...

    await assembler.finalize(state, ledger)
"""

import time
from typing import Optional, Dict, Any, Tuple

from app.utils.redis_client import get_redis, RedisClient
from app.utils.session_manager import (
    SessionManager, SessionMeta, TurnRecord,
)
from app.utils.budget_ledger import (
    BudgetLedger, BudgetSnapshot, NodeBudgetPolicy,
    DEFAULT_NODE_POLICIES,
)
from app.utils.token_counter import count_tokens


class ContextAssembler:
    """
    上下文装配器：管理一次请求的完整生命周期。

    生命周期：
        prepare() → [graph executes] → finalize()
    """

    def __init__(self, total_budget: int = 128_000):
        self.total_budget = total_budget
        self._redis: Optional[RedisClient] = None
        self._session_mgr: Optional[SessionManager] = None

    async def _init(self):
        """懒初始化 Redis 和 SessionManager。"""
        if self._redis is None:
            self._redis = await get_redis()
            self._session_mgr = SessionManager(self._redis)

    @property
    def session_mgr(self) -> SessionManager:
        if self._session_mgr is None:
            raise RuntimeError("ContextAssembler 未初始化，请先调用 prepare()")
        return self._session_mgr

    # ─── 阶段一：准备 ───

    async def prepare(
        self,
        query: str,
        search_mode: str = "hybrid",
        session_id: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], BudgetLedger]:
        """
        请求入口：加载/创建会话，初始化预算账簿。

        Args:
            query: 用户问题
            search_mode: 搜索模式
            session_id: 已有会话 ID（None 则创建新会话）

        Returns:
            (initial_state, budget_ledger)
        """
        await self._init()

        # 1. 获取或创建会话
        session = await self._get_or_create_session(session_id)

        # 2. 生成 Turn ID
        turn_id = SessionManager.generate_turn_id()
        turn_number = session.turns_count + 1

        # 3. 创建预算账簿
        ledger = BudgetLedger(
            session_id=session.session_id,
            total_budget=session.total_budget,
        )
        ledger.begin_turn(turn_number, turn_id)

        # 4. 获取历史记忆（最近 K 个 Turn）
        recent_turns = await self.session_mgr.get_recent_turns(
            session.session_id, k=3
        )

        # 5. 构建初始 AgentState
        initial_state = {
            "query": query,
            "search_mode": search_mode,
            "revision_number": 0,
            # 上下文工程字段
            "session_id": session.session_id,
            "turn_id": turn_id,
            "turn_number": turn_number,
            "episodic_memory": [t.to_dict() for t in recent_turns],
            "semantic_memory": [],  # Phase 3 启用
            "budget_state": ledger.snapshot().__dict__,
            "token_usage_current_turn": {},
            "token_usage_session_total": {
                "estimated_input": session.total_estimated_tokens,
                "actual_input": session.total_actual_tokens,
            },
        }

        # 6. 估算输入 token 用量（粗略）
        estimated_input = self._estimate_input_tokens(query, recent_turns)
        ledger.estimate("router", query)

        # 7. 更新会话活跃时间
        await self.session_mgr.touch_session(session.session_id)

        return initial_state, ledger

    # ─── 阶段二：节点跟踪（在 graph 执行中调用）───

    def record_node_call(
        self,
        ledger: BudgetLedger,
        node_name: str,
        input_text: str,
        output_text: str = "",
    ) -> None:
        """
        记录一次节点 LLM 调用的 Token 消耗。
        在每次 llm.invoke() 后调用（Phase 1: 路由层手动调用，
        Phase 2: 通过 BudgetAwareLLM 自动记录）。
        """
        estimated = ledger.estimate(node_name, input_text)
        estimated_output = count_tokens(output_text) if output_text else 0
        ledger.record(
            node_name=node_name,
            estimated=estimated,
            actual_input=estimated,  # Phase 1: 没有 API usage 时用预估
            actual_output=estimated_output,
        )

    # ─── 阶段三：收尾 ───

    async def finalize(
        self,
        final_state: Dict[str, Any],
        ledger: BudgetLedger,
    ) -> TurnRecord:
        """
        请求出口：归档 Turn、更新会话、持久化。

        Args:
            final_state: LangGraph 执行完成后的 AgentState
            ledger: 预算账簿

        Returns:
            TurnRecord — 归档的 Turn 记录
        """
        await self._init()

        session_id = final_state.get("session_id", "")
        turn_id = final_state.get("turn_id", "")

        # 1. 结束当前 Turn 的记账
        turn_cost = ledger.end_turn()

        # 2. 构建 TurnRecord
        record = TurnRecord(
            turn_id=turn_id,
            turn_number=final_state.get("turn_number", 0),
            query=final_state.get("query", ""),
            plan=final_state.get("plan", []),
            search_results=final_state.get("search_results", []),
            final_report=final_state.get("final_report", ""),
            critique=final_state.get("critique", ""),
            review_status=final_state.get("review_status", ""),
            search_mode=final_state.get("search_mode", "hybrid"),
            token_usage={
                "estimated_input": turn_cost.estimated_total,
                "actual_input": turn_cost.actual_total,
            },
            timestamp=time.time(),
        )

        # 3. 持久化 Turn 到 Redis
        try:
            turn_number = await self.session_mgr.record_turn(session_id, record)

            # 4. 更新会话累计 Token
            session_totals = ledger.get_session_totals()
            await self.session_mgr.update_session(session_id, {
                "last_active": time.time(),
                "turns_count": turn_number,
                "total_estimated_tokens": session_totals["estimated_total"],
                "total_actual_tokens": session_totals["actual_total"],
                "compression_savings": session_totals["compression_savings"],
            })

            # 5. 持久化预算快照
            snapshot = ledger.snapshot()
            await self.session_mgr.save_budget_snapshot(
                session_id, snapshot.__dict__
            )
        except Exception as e:
            # 持久化失败不应阻断用户响应
            import logging
            logging.getLogger("iris.context").warning(
                f"Turn 持久化失败 (session={session_id}, turn={turn_id}): {e}"
            )

        # 6. 检查预估-实际偏差
        alerts = ledger.check_deviation(threshold_pct=25.0)
        if alerts:
            import logging
            logger = logging.getLogger("iris.context")
            for alert in alerts:
                logger.warning(f"Token 偏差告警: {alert}")

        return record

    # ─── 辅助方法 ───

    async def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话信息（给前端展示）。"""
        await self._init()
        meta = await self.session_mgr.load_session(session_id)
        if meta is None:
            return None

        turn_ids = await self._redis.get_turn_ids(session_id)

        return {
            "session_id": meta.session_id,
            "created_at": meta.created_at,
            "last_active": meta.last_active,
            "turns_count": meta.turns_count,
            "total_budget": meta.total_budget,
            "total_estimated_tokens": meta.total_estimated_tokens,
            "total_actual_tokens": meta.total_actual_tokens,
            "compression_savings": meta.compression_savings,
            "status": meta.status,
            "turn_ids": turn_ids[-20:],  # 最近 20 个
        }

    async def _get_or_create_session(
        self, session_id: Optional[str]
    ) -> SessionMeta:
        """获取已有会话或创建新会话。"""
        if session_id:
            meta = await self.session_mgr.load_session(session_id)
            if meta is not None:
                return meta
        return await self.session_mgr.create_session(total_budget=self.total_budget)

    @staticmethod
    def _estimate_input_tokens(
        query: str,
        recent_turns: list,
    ) -> int:
        """粗略估算本次请求的输入 Token。"""
        tokens = count_tokens(query)
        for turn in recent_turns:
            # 每个历史 Turn 大约贡献 500 token（摘要后）
            tokens += 500
        # System prompt 固定开销
        tokens += 2_000
        return tokens

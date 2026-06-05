"""
上下文装配器：会话层与节点层之间的桥梁。

Phase 3 更新：
- 集成 CrossTurnRetriever：语义检索相关历史 Turn
- 集成 CompressionScheduler：异步摘要 + 索引 + 融合编排
- memory_context 现在包含三层：滑动窗口上下文 + 语义检索结果 + 知识融合

用法 (在 routes.py 中):
    assembler = ContextAssembler()
    state, ledger, memory = await assembler.prepare(query, search_mode, session_id)

    # 运行 LangGraph...
    await assembler.finalize(state, ledger)
"""

import time
import asyncio
from typing import Optional, Dict, Any, Tuple, List

from app.utils.redis_client import get_redis, RedisClient
from app.utils.session_manager import (
    SessionManager, SessionMeta, TurnRecord,
)
from app.utils.budget_ledger import (
    BudgetLedger, BudgetSnapshot, NodeBudgetPolicy,
    DEFAULT_NODE_POLICIES,
)
from app.utils.sliding_window import (
    SlidingWindowManager, WindowConfig, AssembledMemory,
)
from app.utils.token_counter import count_tokens
from app.utils.cross_turn_retriever import CrossTurnRetriever, RetrievalResult
from app.utils.compression_scheduler import CompressionScheduler, get_scheduler


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
        self._window_mgr: Optional[SlidingWindowManager] = None
        self._retriever: Optional[CrossTurnRetriever] = None
        self._scheduler: Optional[CompressionScheduler] = None

    async def _init(self):
        """懒初始化所有组件。"""
        if self._redis is None:
            self._redis = await get_redis()
            self._session_mgr = SessionManager(self._redis)
            self._window_mgr = SlidingWindowManager(
                WindowConfig(
                    k=3,
                    total_budget=self.total_budget,
                )
            )
            self._retriever = CrossTurnRetriever()
            self._scheduler = get_scheduler(self._redis)

    @property
    def session_mgr(self) -> SessionManager:
        if self._session_mgr is None:
            raise RuntimeError("ContextAssembler 未初始化，请先调用 prepare()")
        return self._session_mgr

    @property
    def window_mgr(self) -> SlidingWindowManager:
        if self._window_mgr is None:
            raise RuntimeError("ContextAssembler 未初始化，请先调用 prepare()")
        return self._window_mgr

    @property
    def retriever(self) -> CrossTurnRetriever:
        if self._retriever is None:
            raise RuntimeError("ContextAssembler 未初始化，请先调用 prepare()")
        return self._retriever

    @property
    def scheduler(self) -> CompressionScheduler:
        if self._scheduler is None:
            raise RuntimeError("ContextAssembler 未初始化，请先调用 prepare()")
        return self._scheduler

    # ─── 阶段一：准备 ───

    async def prepare(
        self,
        query: str,
        search_mode: str = "hybrid",
        session_id: Optional[str] = None,
        pinned_turn_ids: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], BudgetLedger, AssembledMemory]:
        """
        请求入口：加载/创建会话，装配分层记忆，初始化预算账簿。

        Phase 3: 加入 CrossTurnRetriever 语义检索 + knowledge_fusion。

        Args:
            query: 用户问题
            search_mode: 搜索模式
            session_id: 已有会话 ID（None 则创建新会话）
            pinned_turn_ids: 用户显式引用的历史 Turn ID

        Returns:
            (initial_state, budget_ledger, assembled_memory)
        """
        await self._init()

        # 1. 获取或创建会话
        session = await self._get_or_create_session(session_id)

        # 2. 生成 Turn ID
        turn_id = SessionManager.generate_turn_id()
        turn_number = session.turns_count + 1

        # 3. 加载所有历史 Turn
        all_turn_ids = await self._redis.get_turn_ids(session.session_id)
        all_turns = []
        for tid in all_turn_ids:
            turn_data = await self._redis.get_turn(session.session_id, tid)
            if turn_data:
                all_turns.append(turn_data)

        # 4. 装配分层记忆（滑动窗口）
        memory = self.window_mgr.assemble(
            all_turns=all_turns,
            current_query=query,
            pinned_ids=pinned_turn_ids or [],
        )

        # 5. Phase 3: 语义检索相关历史 Turn
        retrieval_result = self.retriever.retrieve(
            query=query, top_k=3
        )

        # 6. Phase 3: 加载知识融合文本
        knowledge_fusion = ""
        if self._redis:
            fusion_text = await self._redis.hget(
                f"session:{session.session_id}:meta", "knowledge_fusion"
            )
            if fusion_text:
                knowledge_fusion = fusion_text

        # 7. Phase 3: 构建增强版 memory_context
        # 融合三层记忆：滑动窗口 + 语义检索 + 知识融合
        enriched_context = self._build_enriched_context(
            sliding_window_context=memory.memory_context,
            retrieval_context=retrieval_result.context_text,
            knowledge_fusion=knowledge_fusion,
        )

        # 8. 创建预算账簿
        ledger = BudgetLedger(
            session_id=session.session_id,
            total_budget=session.total_budget,
        )
        ledger.begin_turn(turn_number, turn_id)

        # 9. 构建初始 AgentState
        initial_state = {
            "query": query,
            "search_mode": search_mode,
            "revision_number": 0,
            # ─── 上下文工程字段 ───
            "session_id": session.session_id,
            "turn_id": turn_id,
            "turn_number": turn_number,
            # 分层记忆
            "episodic_memory": memory.episodic_memory,
            "semantic_memory": memory.semantic_memory,
            "knowledge_fusion": knowledge_fusion,
            # 预算
            "budget_state": ledger.snapshot().__dict__,
            "token_usage_current_turn": {},
            "token_usage_session_total": {
                "estimated_input": session.total_estimated_tokens,
                "actual_input": session.total_actual_tokens,
            },
            # ─── 增强版 memory_context ───
            "memory_context": enriched_context,
            "window_k": memory.window_k,
            "pinned_turn_ids": pinned_turn_ids or [],
            # ─── Phase 3 新增 ───
            "retrieved_turns": [
                {
                    "turn_id": r.turn_id,
                    "turn_number": r.turn_number,
                    "relevance_score": r.relevance_score,
                    "query_gist": r.query_gist,
                }
                for r in retrieval_result.retrieved_turns
            ],
        }

        # 10. 更新会话活跃时间
        await self.session_mgr.touch_session(session.session_id)

        return initial_state, ledger, memory

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

        Phase 2: 在 routes.py 的 SSE 循环中调用。
        Phase 3: 通过 BudgetAwareLLM 自动记录。
        """
        estimated = ledger.estimate(node_name, input_text)
        estimated_output = count_tokens(output_text) if output_text else 0
        ledger.record(
            node_name=node_name,
            estimated=estimated,
            actual_input=estimated,
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

        Phase 3: 触发异步压缩调度（fire-and-forget）。

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

            # 6. Phase 3: 触发异步压缩（fire-and-forget）
            window_k = final_state.get("window_k", 3)

            # 加载所有 Turn 用于压缩判断
            all_turn_ids = await self._redis.get_turn_ids(session_id)
            all_turns = []
            for tid in all_turn_ids:
                turn_data = await self._redis.get_turn(session_id, tid)
                if turn_data:
                    all_turns.append(turn_data)

            # 异步调度（不阻塞响应）
            if len(all_turns) > window_k:
                asyncio.create_task(
                    self.scheduler.schedule(session_id, all_turns, window_k)
                )

        except Exception as e:
            import logging
            logging.getLogger("iris.context").warning(
                f"Turn 持久化失败 (session={session_id}, turn={turn_id}): {e}"
            )

        # 7. 检查预估-实际偏差
        alerts = ledger.check_deviation(threshold_pct=25.0)
        if alerts:
            import logging
            logger = logging.getLogger("iris.context")
            for alert in alerts:
                logger.warning(f"Token 偏差告警: {alert}")

        return record

    # ─── 历史查询 ───

    async def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话信息（给前端展示）。"""
        await self._init()
        meta = await self.session_mgr.load_session(session_id)
        if meta is None:
            return None

        turn_ids = await self._redis.get_turn_ids(session_id)

        # 获取窗口统计
        all_turns = []
        for tid in turn_ids:
            data = await self._redis.get_turn(session_id, tid)
            if data:
                all_turns.append(data)

        window_stats = self.window_mgr.get_window_stats(all_turns)

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
            "turn_ids": turn_ids[-20:],
            "window_stats": window_stats,
        }

    async def get_session_history(
        self, session_id: str, limit: int = 20
    ) -> Optional[Dict[str, Any]]:
        """
        获取会话的完整历史（含分层记忆视图）。

        Returns:
            {
                session_id, turns_count,
                episodic: [...],  # 全保真窗口中的 Turn
                semantic: [...],  # 压缩窗口中的 Turn
                window_k: int,
                memory_context: str,
            }
        """
        await self._init()
        meta = await self.session_mgr.load_session(session_id)
        if meta is None:
            return None

        # 加载所有 Turn
        turn_ids = await self._redis.get_turn_ids(session_id)
        all_turns = []
        for tid in turn_ids:
            data = await self._redis.get_turn(session_id, tid)
            if data:
                # 反序列化 JSON 字段
                for key in ("plan", "search_results", "token_usage"):
                    if key in data and isinstance(data[key], str):
                        import json
                        try:
                            data[key] = json.loads(data[key])
                        except (json.JSONDecodeError, TypeError):
                            pass
                all_turns.append(data)

        # 使用滑动窗口装配分层视图
        memory = self.window_mgr.assemble(all_turns)

        window_stats = self.window_mgr.get_window_stats(all_turns)

        return {
            "session_id": session_id,
            "turns_count": meta.turns_count,
            "total_budget": meta.total_budget,
            "total_estimated_tokens": meta.total_estimated_tokens,
            "total_actual_tokens": meta.total_actual_tokens,
            "window_k": memory.window_k,
            "window_stats": window_stats,
            "episodic": memory.episodic_memory,
            "semantic": memory.semantic_memory,
            "memory_context": memory.memory_context,
            "created_at": meta.created_at,
            "last_active": meta.last_active,
        }

    async def get_turn_detail(
        self, session_id: str, turn_id: str
    ) -> Optional[Dict[str, Any]]:
        """获取单个 Turn 的完整详情（含原始 report）。"""
        await self._init()

        # 检查会话是否存在
        if not await self._redis.session_exists(session_id):
            return None

        # 获取 Turn 摘要
        turn_data = await self._redis.get_turn(session_id, turn_id)
        if not turn_data:
            return None

        # 获取完整数据（大字段）
        full_data_str = await self._redis.get_turn_full(session_id, turn_id)
        full_data = {}
        if full_data_str:
            import json
            try:
                full_data = json.loads(full_data_str)
            except (json.JSONDecodeError, TypeError):
                pass

        # 反序列化
        import json
        for key in ("plan", "search_results", "token_usage"):
            if key in turn_data and isinstance(turn_data[key], str):
                try:
                    turn_data[key] = json.loads(turn_data[key])
                except (json.JSONDecodeError, TypeError):
                    pass

        return {
            "session_id": session_id,
            **turn_data,
            "full_data": full_data,
        }

    # ─── 辅助方法 ───

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
    def _build_enriched_context(
        sliding_window_context: str,
        retrieval_context: str,
        knowledge_fusion: str,
    ) -> str:
        """
        Phase 3: 构建增强版 memory_context。

        融合三层记忆：
        1. 滑动窗口上下文（Episodic + Semantic）
        2. 语义检索结果（跨轮语义召回）
        3. 知识融合文档（全局研究状态）

        按重要性排列，总长度控制在 ~4000 tokens。
        """
        parts = []

        # 第一优先：滑动窗口（最近 + 历史脉络）
        if sliding_window_context:
            parts.append(sliding_window_context)

        # 第二优先：语义检索（相关但不在窗口内的历史）
        if retrieval_context:
            parts.append("---")
            parts.append(retrieval_context)

        # 第三：知识融合（全局视图）
        if knowledge_fusion:
            parts.append("---")
            parts.append("## 全局知识状态")
            parts.append(knowledge_fusion)

        return "\n\n".join(parts)

    @staticmethod
    def _estimate_input_tokens(
        query: str,
        all_turns: list,
        memory: AssembledMemory,
    ) -> int:
        """估算本次请求的输入 Token。"""
        tokens = count_tokens(query)
        tokens += 2_000  # System prompt
        tokens += memory.total_tokens  # Episodic memory
        tokens += count_tokens(memory.memory_context)
        return tokens

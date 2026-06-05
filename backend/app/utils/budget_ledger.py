"""
Token 预算账簿：会话级 + 节点级双层记账。

Phase 1: 内存版本，后续接入 Redis 持久化。

核心职责：
1. 定义各节点的预算策略（最大输入、溢出处理方式）
2. 每个 LLM 调用前后的预估-实际比对
3. 会话累计 Token 追踪
4. 溢出检测与超标告警
"""

import time
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum


# ─── 预算策略定义 ───

class OverflowPolicy(Enum):
    """溢出策略——节点超预算时的处理方式。"""
    TRUNCATE_OLDEST = "truncate_oldest"       # 截断最旧内容
    SUMMARIZE_CRITIQUE = "summarize_critique"  # 压缩审查意见
    RERANK_AND_TRUNCATE = "rerank_and_truncate"  # Rerank 后截断低相关文档
    COMPRESS_SEARCH = "compress_search_results"  # 压缩搜索结果
    SUMMARIZE_REPORT = "summarize_report_sections"  # 分章节压缩报告
    NONE = "none"  # 不处理（硬截断）


class BudgetPriority(Enum):
    """预算优先级——决定了该节点在压缩循环中的保护级别。"""
    SPEED = "speed"         # 速度和成本优先，宁少勿多
    BALANCED = "balanced"   # 平衡
    RECALL = "recall"       # 召回优先，宁多勿少
    QUALITY = "quality"     # 质量优先，尽量多给上下文


@dataclass
class NodeBudgetPolicy:
    """单个节点的预算策略。"""
    node_name: str
    max_input_tokens: int       # 该节点最大输入 Token
    priority: BudgetPriority    # 优先级
    overflow_policy: OverflowPolicy  # 溢出策略
    model_type: str = "fast"    # 使用的模型类型 (fast/smart)

    def __repr__(self) -> str:
        return (
            f"NodeBudget({self.node_name}: max={self.max_input_tokens}, "
            f"priority={self.priority.value}, overflow={self.overflow_policy.value})"
        )


# ─── 节点预算策略矩阵（对应架构设计文档 3.3 节）───

DEFAULT_NODE_POLICIES: Dict[str, NodeBudgetPolicy] = {
    "router": NodeBudgetPolicy(
        node_name="router",
        max_input_tokens=2_000,
        priority=BudgetPriority.SPEED,
        overflow_policy=OverflowPolicy.TRUNCATE_OLDEST,
        model_type="fast",
    ),
    "planner": NodeBudgetPolicy(
        node_name="planner",
        max_input_tokens=4_000,
        priority=BudgetPriority.BALANCED,
        overflow_policy=OverflowPolicy.SUMMARIZE_CRITIQUE,
        model_type="fast",
    ),
    "researcher": NodeBudgetPolicy(
        node_name="researcher",
        max_input_tokens=40_000,
        priority=BudgetPriority.RECALL,
        overflow_policy=OverflowPolicy.RERANK_AND_TRUNCATE,
        model_type="smart",
    ),
    "writer": NodeBudgetPolicy(
        node_name="writer",
        max_input_tokens=80_000,
        priority=BudgetPriority.QUALITY,
        overflow_policy=OverflowPolicy.COMPRESS_SEARCH,
        model_type="fast",
    ),
    "reviewer": NodeBudgetPolicy(
        node_name="reviewer",
        max_input_tokens=60_000,
        priority=BudgetPriority.BALANCED,
        overflow_policy=OverflowPolicy.SUMMARIZE_REPORT,
        model_type="smart",
    ),
    "refiner": NodeBudgetPolicy(
        node_name="refiner",
        max_input_tokens=80_000,
        priority=BudgetPriority.QUALITY,
        overflow_policy=OverflowPolicy.SUMMARIZE_REPORT,
        model_type="fast",
    ),
}


# ─── 账本数据结构 ───

@dataclass
class TurnCost:
    """单个 Turn 的 Token 消耗明细。"""
    turn_number: int
    turn_id: str
    node_costs: Dict[str, "NodeCost"] = field(default_factory=dict)
    estimated_total: int = 0
    actual_total: int = 0

    @property
    def deviation_pct(self) -> float:
        """预估 vs 实际偏差百分比。"""
        if self.estimated_total == 0:
            return 0.0
        return abs(self.actual_total - self.estimated_total) / self.estimated_total * 100


@dataclass
class NodeCost:
    """单个节点调用的 Token 消耗。"""
    node_name: str
    estimated_input: int = 0     # tiktoken 预估输入
    actual_input: int = 0        # API 返回的实际输入
    actual_output: int = 0       # API 返回的实际输出
    overflow_triggered: bool = False
    compression_applied: bool = False
    tokens_saved: int = 0        # 压缩节省的 Token

    @property
    def actual_total(self) -> int:
        return self.actual_input + self.actual_output


@dataclass
class BudgetSnapshot:
    """当前预算快照——注入到 AgentState 中。"""
    session_id: str
    turn_number: int
    # 分区使用情况
    system_reserve: int = 0      # System Reserve 已用
    episodic_used: int = 0       # Episodic Memory 已用
    semantic_used: int = 0       # Semantic Memory 已用
    working_used: int = 0        # Working Memory 已用
    output_buffer: int = 4_000   # Output Buffer 预留
    # 总计
    total_budget: int = 128_000
    total_used: int = 0
    # 会话累计
    session_estimated_total: int = 0
    session_actual_total: int = 0
    compression_savings: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.total_budget - self.total_used - self.output_buffer)

    @property
    def utilization_pct(self) -> float:
        return self.total_used / self.total_budget * 100


# ─── 账簿管理器 ───

class BudgetLedger:
    """
    Token 预算账簿——会话级记账 + 节点级执行。

    用法:
        ledger = BudgetLedger(session_id="abc123", total_budget=128_000)

        # 节点调用前
        est = ledger.estimate("writer", prompt_text)
        ok, snapshot = ledger.pre_check("writer", prompt_text)
        if not ok:
            prompt_text = apply_overflow("writer", prompt_text)

        # 节点调用后
        ledger.record(node_name="writer", estimated=est, actual_input=5000, actual_output=2000)

        # 获取当前状态
        snapshot = ledger.snapshot()
    """

    def __init__(
        self,
        session_id: str,
        total_budget: int = 128_000,
        policies: Optional[Dict[str, NodeBudgetPolicy]] = None,
    ):
        self.session_id = session_id
        self.total_budget = total_budget
        self.policies = policies or DEFAULT_NODE_POLICIES

        # 会话累计
        self._session_estimated: int = 0
        self._session_actual: int = 0
        self._compression_savings: int = 0

        # 当前 Turn
        self._current_turn_number: int = 0
        self._current_turn_costs: Dict[str, NodeCost] = {}

        # 历史 Turn 明细
        self._turn_history: List[TurnCost] = []

    # ─── Turn 生命周期 ───

    def begin_turn(self, turn_number: int, turn_id: str) -> None:
        """开始新 Turn。"""
        self._current_turn_number = turn_number
        self._current_turn_costs = {}
        # 暂存 turn_id 用于 end_turn
        self._current_turn_id = turn_id

    def end_turn(self) -> TurnCost:
        """结束当前 Turn，归档并返回明细。"""
        tc = TurnCost(
            turn_number=self._current_turn_number,
            turn_id=getattr(self, '_current_turn_id', ''),
            node_costs=dict(self._current_turn_costs),
            estimated_total=sum(c.estimated_input for c in self._current_turn_costs.values()),
            actual_total=sum(c.actual_total for c in self._current_turn_costs.values()),
        )
        self._turn_history.append(tc)
        self._session_estimated += tc.estimated_total
        self._session_actual += tc.actual_total
        return tc

    # ─── 节点级：预检 ───

    def get_policy(self, node_name: str) -> NodeBudgetPolicy:
        """获取节点的预算策略。"""
        return self.policies.get(
            node_name,
            NodeBudgetPolicy(
                node_name=node_name,
                max_input_tokens=40_000,
                priority=BudgetPriority.BALANCED,
                overflow_policy=OverflowPolicy.NONE,
            ),
        )

    def estimate(self, node_name: str, input_text: str) -> int:
        """
        预估输入 Token 数。
        使用简单方法：当前 Phase 1 使用字符估算，
        后续 Phase 2 集成 TokenCounter。
        """
        from app.utils.token_counter import count_tokens

        policy = self.get_policy(node_name)
        return count_tokens(input_text, model=policy.model_type)

    def pre_check(
        self, node_name: str, input_tokens: int
    ) -> Tuple[bool, BudgetSnapshot]:
        """
        节点执行前预算检查。

        Returns:
            (within_budget, snapshot) — 是否在预算内 + 当前快照
        """
        policy = self.get_policy(node_name)
        within = input_tokens <= policy.max_input_tokens

        snapshot = self.snapshot()
        return within, snapshot

    # ─── 节点级：事后记录 ───

    def record(
        self,
        node_name: str,
        estimated: int,
        actual_input: int,
        actual_output: int,
        overflow_triggered: bool = False,
        compression_applied: bool = False,
        tokens_saved: int = 0,
    ) -> NodeCost:
        """记录一次 LLM 调用的实际 Token 消耗。"""
        cost = NodeCost(
            node_name=node_name,
            estimated_input=estimated,
            actual_input=actual_input,
            actual_output=actual_output,
            overflow_triggered=overflow_triggered,
            compression_applied=compression_applied,
            tokens_saved=tokens_saved,
        )
        self._current_turn_costs[node_name] = cost
        if compression_applied:
            self._compression_savings += tokens_saved
        return cost

    # ─── 快照 ───

    def snapshot(self) -> BudgetSnapshot:
        """生成当前预算快照。"""
        current_total = sum(
            c.estimated_input for c in self._current_turn_costs.values()
        )
        return BudgetSnapshot(
            session_id=self.session_id,
            turn_number=self._current_turn_number,
            total_budget=self.total_budget,
            total_used=current_total,
            session_estimated_total=self._session_estimated + current_total,
            session_actual_total=self._session_actual,
            compression_savings=self._compression_savings,
        )

    # ─── 查询 ───

    def get_turn_history(self) -> List[TurnCost]:
        return list(self._turn_history)

    def get_session_totals(self) -> Dict[str, int]:
        return {
            "estimated_total": self._session_estimated,
            "actual_total": self._session_actual,
            "compression_savings": self._compression_savings,
            "net_actual": self._session_actual,
        }

    def check_deviation(self, threshold_pct: float = 20.0) -> List[str]:
        """
        检查所有历史 Turn 的预估-实际偏差。
        偏差超过阈值的返回告警列表。
        """
        alerts = []
        for tc in self._turn_history:
            if tc.deviation_pct > threshold_pct:
                alerts.append(
                    f"Turn {tc.turn_number} ({tc.turn_id}): "
                    f"预估={tc.estimated_total}, 实际={tc.actual_total}, "
                    f"偏差={tc.deviation_pct:.1f}%"
                )
        return alerts

    def __repr__(self) -> str:
        s = self.snapshot()
        return (
            f"BudgetLedger(session={self.session_id}, "
            f"turn={s.turn_number}, "
            f"used={s.total_used}/{s.total_budget}, "
            f"remaining={s.remaining})"
        )

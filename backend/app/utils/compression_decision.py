"""
压缩决策引擎：智能判断何时压缩、压缩到什么层级、驱逐哪些内容。

Phase 4 核心组件——将压缩从"被动触发"升级为"主动决策"。

决策维度：
1. 压缩收益（ROI）：原始 Token / 摘要 Token > 10:1 才值得压缩
2. 召回概率：未来 K 轮内被引用的概率 > 0.3 则不压缩
3. 重要性：高 importance_score 的 Turn 优先保护
4. 时效性：最近的 Turn 优先保留
5. 预算压力：剩余预算越少，压缩越激进
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from app.utils.token_counter import count_tokens


# ─── 压缩层级 ───

class CompressionLevel(Enum):
    """压缩层级——从轻到重。"""
    NONE = 0           # 不压缩（在 Episodic 窗口内）
    TURN_SUMMARY = 1   # Turn 摘要（~500 tokens）
    TOPIC_CLUSTER = 2  # 主题聚类融合（~200 tokens / 主题）
    SESSION_DIGEST = 3 # 会话摘要（~100 tokens）
    EVICT = 4          # 驱逐（仅保留元数据）


# ─── 决策参数 ───

@dataclass
class CompressionConfig:
    """压缩决策的配置参数。"""
    # ROI 阈值
    min_compression_ratio: float = 10.0   # 压缩比 < 10:1 不值得压
    min_tokens_saved: int = 1000          # 至少节省 1000 tokens

    # 召回概率阈值
    recall_window_turns: int = 5          # 预测未来 K 轮内的召回概率
    recall_prob_threshold: float = 0.3    # 召回概率 > 0.3 不压缩

    # 预算压力阈值（剩余预算 / 总预算）
    budget_pressure_low: float = 0.5      # 剩余 > 50%：轻压
    budget_pressure_medium: float = 0.2   # 剩余 20-50%：中压
    # 剩余 < 20%：重压

    # 融合阈值
    semantic_turns_for_fusion: int = 10   # Semantic 中 Turn 数 > 10 触发融合
    episodic_max_tokens: int = 60_000     # Episodic 窗口 Token 上限


# ─── 决策结果 ───

@dataclass
class CompressionDecision:
    """对单个 Turn 的压缩决策。"""
    turn_id: str
    turn_number: int
    current_level: CompressionLevel
    recommended_level: CompressionLevel
    should_compress: bool
    reason: str = ""
    estimated_savings: int = 0
    compression_ratio: float = 0.0


@dataclass
class EvictionPlan:
    """批量驱逐计划。"""
    turns_to_evict: List[str] = field(default_factory=list)
    turns_to_summarize: List[str] = field(default_factory=list)
    turns_to_fusion: List[str] = field(default_factory=list)
    total_tokens_to_free: int = 0
    estimated_tokens_freed: int = 0


# ─── 压缩决策引擎 ───

class CompressionDecisionEngine:
    """
    压缩决策引擎。

    用法:
        engine = CompressionDecisionEngine()

        # 判断单个 Turn
        decision = engine.decide(turn, budget_pressure=0.3)

        # 批量决策
        plan = engine.plan_eviction(
            all_turns, window_k=3, budget_pressure=0.15
        )
    """

    def __init__(self, config: Optional[CompressionConfig] = None):
        self.config = config or CompressionConfig()

    # ─── 单个 Turn 决策 ───

    def decide(
        self,
        turn: Dict[str, Any],
        turn_index: int,          # 0 = 最旧
        total_turns: int,          # 总会话 Turn 数
        window_k: int = 3,
        budget_pressure: float = 0.5,
        is_pinned: bool = False,
    ) -> CompressionDecision:
        """
        决定单个 Turn 是否需要压缩以及压缩到什么层级。

        Args:
            turn: Turn 数据 dict
            turn_index: 在全部 Turn 中的位置（0-based，越大越新）
            total_turns: 总会话 Turn 数
            window_k: 当前全保真窗口大小
            budget_pressure: 预算压力（0-1，越小压力越大）
            is_pinned: 是否被用户显式引用

        Returns:
            CompressionDecision
        """
        turn_id = turn.get("turn_id", "")
        turn_number = turn.get("turn_number", 0)
        distance_from_latest = total_turns - 1 - turn_index

        # 1. Pinned Turn：永不压缩
        if is_pinned:
            return CompressionDecision(
                turn_id=turn_id,
                turn_number=turn_number,
                current_level=CompressionLevel.NONE,
                recommended_level=CompressionLevel.NONE,
                should_compress=False,
                reason="用户引用的 Turn，永不压缩",
            )

        # 2. 在 Episodic 窗口内：不压缩
        if distance_from_latest < window_k:
            return CompressionDecision(
                turn_id=turn_id,
                turn_number=turn_number,
                current_level=CompressionLevel.NONE,
                recommended_level=CompressionLevel.NONE,
                should_compress=False,
                reason=f"在 Episodic 窗口内 (K={window_k})",
            )

        # 3. 在 Semantic 窗口中：决定压缩层级
        raw_tokens = self._estimate_turn_tokens(turn)
        summary_tokens = 500  # Turn Summary 预估

        compression_ratio = raw_tokens / max(summary_tokens, 1)
        estimated_savings = raw_tokens - summary_tokens

        # 3a. 压缩 ROI 检查
        if compression_ratio < self.config.min_compression_ratio:
            return CompressionDecision(
                turn_id=turn_id,
                turn_number=turn_number,
                current_level=CompressionLevel.TURN_SUMMARY,
                recommended_level=CompressionLevel.NONE,
                should_compress=False,
                reason=f"压缩比 {compression_ratio:.1f}x < 阈值 {self.config.min_compression_ratio:.0f}x",
                compression_ratio=compression_ratio,
            )

        # 3b. 召回概率检查
        recall_prob = self._estimate_recall_probability(
            distance_from_latest, importance_score=float(
                turn.get("importance_score", 0.5)
            ),
        )
        if recall_prob > self.config.recall_prob_threshold:
            return CompressionDecision(
                turn_id=turn_id,
                turn_number=turn_number,
                current_level=CompressionLevel.TURN_SUMMARY,
                recommended_level=CompressionLevel.NONE,
                should_compress=False,
                reason=f"召回概率 {recall_prob:.2f} > 阈值 {self.config.recall_prob_threshold}",
                compression_ratio=compression_ratio,
            )

        # 3c. 根据预算压力选择层级
        if budget_pressure > self.config.budget_pressure_low:
            # 轻压：只用 Turn Summary
            level = CompressionLevel.TURN_SUMMARY
        elif budget_pressure > self.config.budget_pressure_medium:
            # 中压：根据 Turn 的新旧程度选择
            if distance_from_latest > total_turns * 0.7:
                level = CompressionLevel.TOPIC_CLUSTER
            else:
                level = CompressionLevel.TURN_SUMMARY
        else:
            # 重压：激进压缩
            if distance_from_latest > total_turns * 0.5:
                level = CompressionLevel.SESSION_DIGEST
            elif distance_from_latest > total_turns * 0.3:
                level = CompressionLevel.TOPIC_CLUSTER
            else:
                level = CompressionLevel.TURN_SUMMARY

        return CompressionDecision(
            turn_id=turn_id,
            turn_number=turn_number,
            current_level=CompressionLevel.TURN_SUMMARY,
            recommended_level=level,
            should_compress=True,
            reason=f"预算压力={budget_pressure:.1%}, 距离={distance_from_latest}, 层级={level.name}",
            estimated_savings=estimated_savings,
            compression_ratio=compression_ratio,
        )

    # ─── 批量驱逐规划 ───

    def plan_eviction(
        self,
        all_turns: List[Dict[str, Any]],
        window_k: int = 3,
        budget_pressure: float = 0.5,
        tokens_to_free: int = 0,
        pinned_ids: Optional[List[str]] = None,
    ) -> EvictionPlan:
        """
        规划批量驱逐：当预算紧张时，选择哪些 Turn 压缩/驱逐。

        Args:
            all_turns: 所有 Turn（按时间升序排列）
            window_k: 全保真窗口大小
            budget_pressure: 预算压力（0-1）
            tokens_to_free: 需要释放的 Token 数
            pinned_ids: 用户引用的 Turn ID 列表

        Returns:
            EvictionPlan
        """
        pinned_ids = pinned_ids or []
        plan = EvictionPlan(total_tokens_to_free=tokens_to_free)

        if not all_turns or len(all_turns) <= window_k:
            return plan

        total_turns = len(all_turns)

        # 对超出窗口的每个 Turn 做决策
        decisions = []
        for i, turn in enumerate(all_turns):
            if i >= total_turns - window_k:
                break  # 在窗口内的不处理

            decision = self.decide(
                turn=turn,
                turn_index=i,
                total_turns=total_turns,
                window_k=window_k,
                budget_pressure=budget_pressure,
                is_pinned=turn.get("turn_id", "") in pinned_ids,
            )

            if decision.should_compress:
                decisions.append(decision)

        # 按压缩收益降序排列（收益大的先压）
        decisions.sort(key=lambda d: d.estimated_savings, reverse=True)

        # 分配决策
        freed = 0
        for d in decisions:
            if tokens_to_free > 0 and freed >= tokens_to_free:
                break

            if d.recommended_level == CompressionLevel.TURN_SUMMARY:
                plan.turns_to_summarize.append(d.turn_id)
            elif d.recommended_level == CompressionLevel.TOPIC_CLUSTER:
                plan.turns_to_fusion.append(d.turn_id)
            elif d.recommended_level in (
                CompressionLevel.SESSION_DIGEST,
                CompressionLevel.EVICT,
            ):
                plan.turns_to_evict.append(d.turn_id)

            freed += d.estimated_savings

        plan.estimated_tokens_freed = freed
        return plan

    # ─── 启发式估算 ───

    def _estimate_turn_tokens(self, turn: Dict[str, Any]) -> int:
        """估算 Turn 的 Token 数。"""
        text = (
            str(turn.get("query", ""))
            + str(turn.get("final_report", ""))
            + str(turn.get("plan", ""))
            + str(turn.get("search_results", ""))
        )
        return count_tokens(text)

    def _estimate_recall_probability(
        self,
        distance_from_latest: int,
        importance_score: float = 0.5,
    ) -> float:
        """
        估算一个 Turn 在未来 K 轮内被引用的概率。

        启发式：
        - 距离越远，被引用概率越低（指数衰减）
        - 重要度越高，被引用概率越高
        - 话题标签匹配度（TODO: 跨 Turn 话题相关性）
        """
        # 距离衰减
        distance_factor = max(0.05, 1.0 - distance_from_latest / 20)

        # 综合概率
        prob = distance_factor * 0.5 + importance_score * 0.5

        return min(1.0, max(0.0, prob))

    def get_budget_pressure(self, remaining: int, total: int) -> float:
        """计算预算压力（0 = 压力最大, 1 = 无压力）。"""
        if total == 0:
            return 0.0
        return max(0.0, min(1.0, remaining / total))

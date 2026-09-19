"""检索计划包（S6 DAG 内核 + S7 计划 Schema）。

对外只暴露两样东西：
    from app.graph.planner import dag                 # 调度内核
    from app.graph.planner import SearchPlan          # LLM 输出契约

这样调用方（planner 节点 / researcher 节点 / plan_review 节点）不必知道
内部文件是怎么拆的。
"""

from app.graph.planner.dag import (
    CANCELED,
    DEFAULT_MAX_STEPS,
    FAILED,
    PENDING,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    WAITING,
    PlanError,
    assemble,
    cancel_remaining,
    needs_confirm,
    ready,
    resolve_max_steps,
    settle,
    validate_plan,
)
from app.graph.planner.schemas import SearchPlan, SearchTask

__all__ = [
    # 状态常量（7 态状态机，前端文案映射的唯一来源）
    "PENDING",
    "WAITING",
    "QUEUED",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELED",
    # 类
    "PlanError",
    "SearchPlan",
    "SearchTask",
    # 调度内核
    "DEFAULT_MAX_STEPS",
    "assemble",
    "cancel_remaining",
    "needs_confirm",
    "ready",
    "resolve_max_steps",
    "settle",
    "validate_plan",
]

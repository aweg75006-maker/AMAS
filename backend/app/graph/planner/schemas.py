"""检索计划的 LLM 输出契约（S7）。

【改造前后对比 —— 这是 S7 的全部意义】
改造前（nodes/planner.py:42-44）：
    plans = [p.strip() for p in response.content.split(",")]
用逗号切分 LLM 的自然语言回答，没有任何结构约束，
所以无法表达"哪条检索依赖哪条"，也无法做参数校验。

改造后：LLM 直接输出下面这个 Pydantic 模型的 JSON，
于是计划变成**可校验的结构**，可以喂给 dag.validate_plan() 做四项校验。

【决策 D4：plan 字段双写过渡】
`AgentState.plan: List[str]` **必须保留**，因为下游三处都在读它：
  · Writer 的 prompt
  · TurnRecordDict（历史记录落库结构）
  · TestRetrievalHints（既有测试断言）
所以本轮是"双写"：`search_tasks`（新链路）+ `plan`（旧字段），
而且两者必须由**同一个函数** `_parse_plan` 同时产出 —— 防止多处各自构造导致不一致（全局风险 R7）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# 只允许这两个检索工具 —— 用 Literal 而不是 str，
# 模型输出别的工具名时会在 Pydantic 校验阶段就被拒，
# 不需要等 dag.validate_plan 去 registry 里查了才发现。
RetrievalTool = Literal["rag.retrieve_candidates", "web.retrieve_candidates"]

# 召回通道，仅用于前端展示"这条任务主要覆盖哪条通道"
RetrievalChannel = Literal["dense", "bm25", "web"]


class SearchTask(BaseModel):
    """一个可独立执行、可失败隔离的检索子任务。

    id:         任务 id，形如 t1、t2；同时作为 depends_on 的引用键
    tool:       检索工具名（见 RetrievalTool，只有两个合法值）
    params:     工具参数，通常只有 query
                ⚠️ 不要生成 knowledge_base_id —— 它属于 server_filled，
                   由服务端从图状态注入，模型看不到也不该传（S2 的安全边界）
    depends_on: 前置任务 id 列表。
                **留空 = 自动串行**（dag.assemble 会补成"依赖上一步"），
                这不是"无依赖"——默认串行的原因见 dag.assemble 的说明
    channel:    该任务主要覆盖哪条召回通道（dense / bm25 / web），仅用于展示
    note:       该任务覆盖哪块证据缺口，一句话，前端直接显示
    """

    id: str = Field(description="任务 id，形如 t1、t2")
    tool: RetrievalTool
    params: dict[str, Any] = Field(
        default_factory=dict, description="工具参数，通常只有 query"
    )
    depends_on: list[str] = Field(
        default_factory=list, description="前置任务 id；留空则自动串行"
    )
    channel: RetrievalChannel | None = Field(
        default=None, description="该任务主要覆盖哪条召回通道"
    )
    note: str = Field(
        default="", max_length=200, description="该任务覆盖哪块证据缺口，用于前端展示"
    )


class SearchPlan(BaseModel):
    """一轮检索的完整计划（LLM 的直接输出目标）。

    rationale 是"为什么这样拆解"的一句话说明，
    既方便人工排查（模型是不是乱拆的），也是面试时能讲的"可解释性"。
    """

    tasks: list[SearchTask] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=500, description="为什么这样拆解")


# ---------------------------------------------------------------------------
# S7 待接线清单（Demo 阶段：Schema 已就绪，解析与 prompt 尚未切换）
# ---------------------------------------------------------------------------
# ① app/harness/prompts/planner.research.v1.txt —— 改成要求输出 SearchPlan 的 JSON：
#        {"tasks": [{"id": "t1", "tool": "rag.retrieve_candidates",
#                    "params": {"query": "..."}, "depends_on": [],
#                    "channel": "dense", "note": "覆盖…"}],
#         "rationale": "一句话说明拆解思路"}
#    规则要写进 prompt：
#      · tool 只能是 rag.retrieve_candidates 或 web.retrieve_candidates；
#      · 最多 6 个任务；
#      · 只有"后一个任务需要用到前一个任务的结果"时才写 depends_on，否则留空让它们并发；
#      · 不要生成 knowledge_base_id 参数，服务端会注入。
#    ⚠️ 全局风险 R4：get_prompt_template 带 @lru_cache（harness/registry.py:144），
#       改完 prompt **必须重启进程**，否则读到的是旧模板（表现为"假失败"）。
#
# ② app/graph/nodes/planner.py —— plan_node 双写 + 新增 _parse_plan：
#        search_tasks, plans = _parse_plan(response.content)
#        return {"plan": plans, "search_tasks": search_tasks}   # ★ 双写
#
#        def _parse_plan(content: str) -> tuple[list[dict], list[str]]:
#            """解析为 (search_tasks, legacy_plan)；四类脏格式全部走回退。"""
#            raw = (content or "").strip()
#            if raw.startswith("```"):                      # 容忍 Markdown 围栏
#                raw = raw.strip("`").removeprefix("json").strip()
#            try:
#                plan = SearchPlan.model_validate_json(raw)
#            except Exception:
#                legacy = [p.strip() for p in raw.split(",") if p.strip()]  # 旧路径兜底
#                return [], legacy
#            try:
#                steps = dag.validate_plan([t.model_dump() for t in plan.tasks],
#                                          max_steps=dag.resolve_max_steps(budget_state))
#            except Exception:
#                # 工具不存在 / 成环 / 参数非法 → 退回关键词，绝不让整轮研究挂掉
#                return [], [t.params.get("query", "") for t in plan.tasks
#                            if t.params.get("query")]
#            return steps, [s["params"].get("query", "") for s in steps
#                           if s["params"].get("query")]
#
# ③ app/graph/state.py（AgentState，约 :114-122 区域）追加两个字段：
#        search_tasks: List[Dict[str, Any]]                 # 检索子任务 DAG
#        search_task_results: Dict[str, List[Dict[str, Any]]]  # 子任务 id → 候选列表

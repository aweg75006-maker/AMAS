"""检索计划人工确认点（S9 骨架）。

===============================================================================
【一句话目标】
===============================================================================
把 HITL 从"整个工作流暂停一次"细化成"**选择执行哪几条检索**"。

===============================================================================
【★ 面试要点：两级 HITL，两种语义】
===============================================================================
本项目有**两个独立的人工检查点**，不是同一个开关的两个档位：

  ┌ 检索前（本文件 plan_review） = **选择式**
  │   把 N 条检索任务列出来，让人勾选跑哪几条。
  │   语义是"减法"：默认全跑，你只负责去掉不要的。
  │
  └ 写作前（既有 hitl_pause_before=writer） = **注入式**
      让人补充要求/约束，再进 Writer。
      语义是"加法"：默认没有额外要求，你负责加上去。

两者**实现机制相同**（都复用 LangGraph 原生 `interrupt()` + SQLite checkpoint
+ `/api/chat/resume` 通道），只是回收的字段不同（本节点回收 `approved_ids`）。

===============================================================================
【⚠️ 一个容易踩的坑】
===============================================================================
**不要把 `plan_review` 塞进 `hitl_pause_before` 的映射里**
（`app/graph/runtime.py:26-35` 的 `_should_pause_before`，它现在把 `writer`
映射到 `{writer, refiner}`）。两者是独立的两级检查点 ——
一旦混进同一个映射，写作前的注入式检查点会被意外改写，
表现为"勾选完检索任务后，写作前的确认不见了"。

===============================================================================
【为什么用 interrupt() 而不是自己搞一套暂停】
===============================================================================
interrupt() 的恢复点由 LangGraph 的 checkpoint 保证：
调 `Command(resume=...)` 时会**从中断处继续**，不会重跑前面的节点。
自己实现暂停要么重跑整条链路（浪费 token），要么维护一份"跑到哪了"的外部状态
（与 checkpoint 形成两套真相，迟早不一致）。

===============================================================================
⚠️ Demo 阶段实现状态
===============================================================================
本文件是**骨架**：节点签名、中断载荷结构、边界处理要点均已就位，函数体留空。
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

logger = get_logger("iris.graph.plan_review")


def review_plan_node(state: dict[str, Any]) -> dict[str, Any]:
    """把检索子任务清单交给人勾选；单任务不打扰用户。

    【返回语义】
      · 不需要确认（单任务）→ 返回 `{}`，即"不改动 state"，直接往下走
      · 需要确认 → interrupt() 会把当前状态挂起并落 checkpoint，
        恢复时**本函数会从 interrupt() 那一行重新执行**，
        此时 interrupt() 返回用户在 resume 时传进来的 decision。

    【中断载荷结构（前端按 kind 分发渲染）】
        {
            "kind": "search_plan_review",
            "prompt": "准备执行 4 条检索，可取消其中部分后继续。",
            "tasks": [
                {"id": "t1", "tool": "rag.retrieve_candidates",
                 "query": "...", "channel": "dense", "note": "覆盖…"},
                ...
            ],
        }
      注意任务是**扁平化**的（query 提出来、channel/note 原样带），
      而不是把整个 task dict 丢过去 —— 前端不需要理解 params 的嵌套结构。

    【⚠️ 全局风险 R8：全员取消会产出空 DAG】
    用户把 4 条全取消 → 检索阶段拿到空计划 → 报告没有任何依据。
    处理策略：**approved_ids 为空时退回"全选"**，而不是产出空计划。
    宁可尊重"默认全跑"的语义，也不要生成一份没有证据的报告。

    【实现要点】
      1. `tasks = list(state.get("search_tasks") or [])`
      2. `if not dag.needs_confirm(tasks): return {}`
         （needs_confirm 的阈值是 len > 1，见 graph/planner/dag.py）
      3. `decision = interrupt({...})` —— 载荷见上
      4. 取 approved_ids：`(decision or {}).get("approved_ids")`，
         并防御 decision 不是 dict 的情况（用户直接 resume 会传空）
      5. 全空 → 退回全选（R8 的缓解措施）
      6. 遍历 tasks 分类：
         · id 在 approved 里 → kept（状态不变）
         · 否则 → dropped，且 `status = dag.CANCELED`
           （注意：被取消的任务**仍要留在列表里**，
             前端需要显示"已取消"这一行，而不是让它凭空消失）
      7. 返回 `{"search_tasks": kept + dropped}`
    """
    pass  # TODO(S9): 按上面 7 步实现


# ---------------------------------------------------------------------------
# S9 待接线清单（Demo 阶段：节点为骨架，图与 API 尚未接线）
# ---------------------------------------------------------------------------
# ① app/graph/graph.py —— 加节点 + 两条边：
#        workflow.add_node("plan_review", wrap_node("plan_review", review_plan_node))
#        workflow.add_edge("planner", "plan_review")
#        workflow.add_edge("plan_review", "researcher")
#    即把原来的 planner → researcher 直连，改为中间插一个检查点。
#
# ② app/api/schemas.py（约 :17-19）—— ResumeChatRequest 加字段：
#        approved_ids: Optional[List[str]] = None    # ★ 检索计划确认点用
#    带默认值 None，旧前端请求体仍可正常解析（不破坏兼容）。
#
# ③ app/api/routes_chat.py（约 :140）—— resume 时透传：
#        workflow_input=Command(resume={
#            "human_input": request.human_input,
#            "approved_ids": request.approved_ids,   # ★ 新增
#        }),
#
# ④ SSE 侧不用改：routes_chat.py:215-223 已经在处理 `__interrupt__` 并推
#    `__hitl_pause__`，新检查点自动复用这条通道。
#    前端只需按 `data.kind` 分发（"search_plan_review" → 计划卡片；
#    写作前注入式 → 原有的输入框）。
#
# ⑤ 测试：扩展 tests/test_langgraph_hitl.py 三个用例 ——
#        test_plan_review_skips_interrupt_for_single_task    单任务不打断
#        test_plan_review_returns_full_plan_when_no_selection 全不选 → 退回全选（R8）
#        test_plan_review_marks_dropped_tasks_canceled        取消项状态是 canceled

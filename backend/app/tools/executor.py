"""工具执行外壳（S3 + S4）。

【这一层是干什么的】
把 researcher 子图里原本重复三遍的这段代码收口到一处：
    调 runtime → 记快照 → if not result.ok: logger.warning + continue

重复的坏处不只是难看，更关键的是**失败信息不落状态** ——
只打了一行日志，前端看不到"哪条检索失败了"，用户只能看到"研究中"然后报告变短了。

收口之后节点侧从 10 行降到 1 行：`executor.call(...)`。

【S3 与 S4 的分工】
- S3（执行外壳）：参数校验 + 失败隔离（默认返回 None，required=True 才抛）+ 快照收集；
- S4（工具级进度）：`progress_sink` 把工具内部攒的进度逐条回放给 SSE。

【为什么进度要用"返回值回放"而不是回调（决策 D2）】
工具是**同步函数**，跑在 `ToolRuntime._run_with_timeout` 里的 ThreadPoolExecutor 子线程；
而 SSE 的 progress_writer 属于主事件循环。在子线程里直接回调会跨线程碰 asyncio loop。
所以让工具把进度攒进返回值（`ToolOutcome`），由本类在**主线程**逐条回放。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger
from app.tools.registry import get_tool_registry
from app.tools.runtime import ToolRuntime
from app.tools.validation import InvalidToolParams, validate_params

logger = get_logger("iris.tools.executor")


# 进度回调的签名：(stage, message, progress, details) -> None
# 注意：这个回调只在主线程被调用（见文件头 D2 的说明）。
ProgressSink = Callable[[str, str, "int | None", dict[str, Any]], None]


class ToolExecutionError(Exception):
    """标记为 required 的工具最终失败时抛出。

    默认情况下工具失败是**被隔离**的（返回 None，不打断节点）—— 这是
    "单条检索失败不影响整体报告"的基础。只有调用方明确说"这个必须成功"
    时才会走到这里。
    """


class ToolExecutor:
    """一次节点执行内的工具调用收集器。

    生命周期：在一个节点函数内部创建 → 调用 N 次 `call()` → 把 `self.runs`
    写回 `state["tool_runs"]`。

    为什么不复用同一个 ToolRuntime 实例跨节点？
    因为 ToolRuntime 绑定 node_name，而 node_name 决定了从 harness 清单里
    加载哪一组工具的超时/重试配置 —— 跨节点复用会拿错配置。
    """

    def __init__(
        self,
        *,
        node_name: str,
        state: dict[str, Any] | None = None,
        progress_sink: ProgressSink | None = None,
    ) -> None:
        self._node_name = node_name
        # state 用来给 S2 的 server_filled 注参提供数据源（knowledge_base_id 等）
        self._state = state or {}
        self._runtime = ToolRuntime(node_name=node_name)
        # S4：工具级进度的出口；为 None 表示这个节点不打算上报工具级进度
        self._sink = progress_sink
        # 本节点内所有工具调用的快照，供节点写回 state["tool_runs"]
        self.runs: list[dict[str, Any]] = []

    def call(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        required: bool = False,
        input_summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Any | None:
        """执行一个已注册工具。

        返回：成功 → 工具的返回值（若工具返回 ToolOutcome，这里是拆封后的裸值）；
              失败 → None（默认隔离），或 required=True 时抛 ToolExecutionError。

        执行顺序：
          1. 参数校验（S1 的 validate_params，与 LLM function schema 同源）
          2. runtime 执行（内部做 server_filled 注参 → 超时 → 重试 → 快照）
          3. 收集快照
          4. S4：回放工具级进度
          5. 失败隔离 / 按 required 决定是否抛
        """
        spec = get_tool_registry().get(tool_name)

        # ── 第 1 步：参数校验。放在执行之前，坏参数不会产生执行快照 ──
        try:
            checked = validate_params(spec, payload)
        except InvalidToolParams as exc:
            self._fail(tool_name, "TOOL_INVALID_PARAMS", str(exc), required)
            return None

        # ── 第 2 步：执行（超时 / 重试 / 快照 / S2 注参都在 runtime 内部完成）──
        result = self._runtime.run_registered(
            tool_name,
            checked,
            state=self._state,
            input_summary=input_summary or checked,
            metadata=metadata,
        )

        # ── 第 3 步：收集快照。注意失败也要收集 —— 前端要能显示"这条失败了" ──
        if result.run is not None:
            self.runs.append(result.run.to_dict())

        # ── 第 4 步（S4）：在主线程把工具攒的进度逐条回放 ──
        for item in getattr(result, "progress", ()):  # getattr 兜底，兼容旧 runtime
            if self._sink is not None:
                self._sink(item.stage, item.message, item.progress, item.details)

        # ── 第 5 步：失败处理 ──
        if not result.ok:
            # 快照里已经带了 error_code（TOOL_TIMEOUT / TOOL_FAILED），直接复用，
            # 不要在两层各自判断一次"是不是超时"，否则两处会漂移。
            self._fail(
                tool_name,
                (result.run.error_code if result.run else "TOOL_FAILED"),
                (result.run.error_message if result.run else ""),
                required,
            )
            return None

        return result.value

    def _fail(self, tool_name: str, code: str, message: str, required: bool) -> None:
        """统一的失败出口：先记日志，再按 required 决定是否升级成异常。"""
        logger.warning(
            "tool_call_failed",
            extra={
                "node_name": self._node_name,
                "tool_name": tool_name,
                "error_code": code,
                # 日志里可以留内部信息（便于排查），但对用户展示的文案不应直接用它
                "error_message": message[:300],
            },
        )
        if required:
            raise ToolExecutionError(f"{tool_name}: {message or code}")


# ---------------------------------------------------------------------------
# S3 待接线清单（Demo 阶段：外壳已就绪，节点侧收敛尚未执行）
# ---------------------------------------------------------------------------
# 目标文件：app/graph/nodes/researcher.py
#
#   ① retrieve_local  （原 :270-291）
#      executor = ToolExecutor(node_name="researcher", state=state["workflow_state"],
#                              progress_sink=_tool_progress_sink(progress_writer))
#      documents = executor.call("rag.retrieve_candidates", {...}, input_summary=query)
#      → return {"local_candidates": candidates, "tool_runs": executor.runs}
#
#   ② retrieve_web    （原 :299-320）      同上，工具换成 web.retrieve_candidates
#
#   ③ evaluate_evidence（原 :384-428）
#      assessment = executor.call("rag.relevance_grade", {...}, input_summary=...) or {}
#      ⚠️ 重点保护：原 :410-428 那段"防御性解析"必须原样保留（全局风险 R5）——
#         它负责在 LLM 返回脏格式时兜底，删了会让整轮研究失败。
#
#   ④ 删除 _append_tool_run（原 :182-186）—— 收敛后不再需要
#
# 验收红线：test_researcher_tool_registry.py:78-82 断言工具调用顺序为
#   [rag.retrieve_candidates, web.retrieve_candidates, rag.relevance_grade]
# 收敛只改"怎么写"，不改"什么顺序调"，改完这条断言必须仍然绿。

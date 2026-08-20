import asyncio
import time
from collections.abc import Callable

from langchain_core.runnables import RunnableConfig

# 全局设置（兜底用的默认重试/超时值来自这里）
from app.core.config import settings
# 自定义配置异常（节点在 manifest 里没配时会被捕获）
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.graph.state import AgentState
# 文本清洗：剥离 state 顶层字符串里可能混入的孤立代理字符（surrogate），
# 否则下游任何 encode('utf-8')（LLM 请求序列化 / sha256 / json.dumps）都会被炸
from app.utils.text_sanitize import sanitize_state_strings
# 关键：从 harness 注册表按节点名取「这个节点在 manifest 里配的 max_retries / timeout_seconds」
# —— 这正是之前聊的 default_research.json 里每个节点的重试/超时「真正生效」的地方。
from app.harness.registry import get_harness_node
# LangGraph 提供的人工介入（Human-In-The-Loop）中断机制
from langgraph.types import interrupt


logger = get_logger("iris.graph.runtime")


def _should_pause_before(requested_node: str | None, node_name: str) -> bool:
    """Return whether the selected human checkpoint applies to this node.

    In follow-up turns, edits to an existing report are routed directly to the
    refiner instead of the writer.  From the user's perspective both are
    writing operations, so the "before writing" checkpoint must cover both.
    """
    if requested_node == "writer":
        return node_name in {"writer", "refiner"}
    return requested_node == node_name


class WorkflowNodeExecutionError(Exception):
    """节点在「重试耗尽 / 超时」后抛出的异常，表示这个节点最终执行失败。

    上层（图编排）捕获它后，可以决定是中止整个工作流还是做别的处理。
    """

    def __init__(
        self,
        node_name: str,
        original: Exception,
        *,
        attempts: int,
        duration_ms: int,
    ):
        super().__init__(str(original))
        self.node_name = node_name          # 失败的是哪个节点
        self.original = original            # 最后一次的真实异常
        self.attempts = attempts            # 一共尝试了多少次（含首次）
        self.duration_ms = duration_ms      # 从第一次尝试到最终失败的总耗时（毫秒）
        # 错误码：如果是因为超时才失败，归为 TIMEOUT；否则是 FAILED
        self.error_code = (
            "WORKFLOW_NODE_TIMEOUT"
            if isinstance(original, TimeoutError)
            else "WORKFLOW_NODE_FAILED"
        )


def wrap_node(
    node_name: str,
    fn: Callable[[AgentState], dict],
) -> Callable[[AgentState], object]:
    """给一个工作流节点函数「套壳」，加上两层运行时能力：

    1) 人工暂停（HITL）：如果状态里标记了「在某节点前暂停」，执行前先中断，
       等人补充输入再继续；
    2) 重试 + 超时：按 manifest（或全局兜底）配置的 max_retries / timeout_seconds
       反复执行，失败就退避重试，全部失败则抛 WorkflowNodeExecutionError。

    返回的是被包装后的异步函数，图构建时把它当作真正的节点挂上去。
    """
    async def wrapped(
        state: AgentState,
        config: RunnableConfig | None = None,
    ) -> dict:
        # 复制一份状态，避免直接改原始 state
        effective_state = dict(state)
        # ---- ⓪ 入口清洗：剥离顶层字符串中的孤立代理字符 ----
        # 用户输入 / 上游数据里可能混入这类非法字符（如终端粘贴带进来的脏字节），
        # 它们会让节点内部任何 utf-8 编码点（LLM 请求体序列化、sha256、json.dumps）
        # 抛 UnicodeEncodeError: surrogates not allowed，且重试必然失败。
        sanitize_state_strings(effective_state)

        # ---- ① 人工介入（HITL）暂停逻辑 ----
        # 如果当前节点被标记成「需要在执行前暂停等人」，就调用 interrupt 中断工作流
        if _should_pause_before(effective_state.get("hitl_pause_before"), node_name):
            human_input = interrupt(
                {
                    "pause_node": node_name,
                    "prompt": f"工作流将在节点「{node_name}」执行前暂停，等待人工补充。",
                    "thread_id": (config or {}).get("configurable", {}).get("thread_id", ""),
                }
            )
            # 把人填回来的内容整理成字符串，写回状态
            if isinstance(human_input, dict):
                human_input = human_input.get("human_input", "")
            effective_state["human_input"] = str(human_input or "").strip()
            effective_state["hitl_pause_before"] = ""

        # ---- ② 读取这个节点在 manifest 里的重试/超时配置 ----
        # 先从注册表取节点配置；如果 manifest 里没有这个节点（ConfigurationError），就回退到 None
        try:
            harness_node = get_harness_node(node_name)
        except ConfigurationError:
            harness_node = None
        # 优先用 manifest 里节点自己配的 max_retries / timeout_seconds；
        # 没配（为 None）时才用 settings 里的全局默认值兜底。
        configured_retries = (
            harness_node.max_retries
            if harness_node is not None and harness_node.max_retries is not None
            else settings.workflow_node_max_retries
        )
        configured_timeout = (
            harness_node.timeout_seconds
            if harness_node is not None and harness_node.timeout_seconds is not None
            else settings.workflow_node_timeout_seconds
        )
        # 计算最终参数（做个下限保护，避免负数或 0 超时）
        max_retries = max(0, configured_retries)        # 允许的最大重试次数
        attempts_allowed = max_retries + 1              # 总尝试次数 = 首次 + 重试
        timeout = max(0.1, configured_timeout)          # 单次调用超时（秒），至少 0.1s
        backoff = max(0.0, settings.workflow_retry_backoff_seconds)  # 退避间隔（秒）
        started_at = time.time()
        last_error: Exception | None = None            # 记录最后一次出错信息

        # ---- ③ 重试循环：最多尝试 attempts_allowed 次 ----
        for attempt in range(1, attempts_allowed + 1):
            try:
                logger.info(
                    "workflow_node_attempt_started",
                    extra={
                        "node_name": node_name,
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "timeout_seconds": timeout,
                    },
                )
                # 用 wait_for 给 fn 套上超时；fn 本身是同步函数，这里用 to_thread 丢到线程里跑
                result = await asyncio.wait_for(
                    asyncio.to_thread(fn, effective_state),
                    timeout=timeout,
                )
                # 如果这是重试后成功的（attempt>1），在结果里打一个重试标记，方便上层追踪
                if attempt > 1:
                    result = {
                        **result,
                        "_workflow_retry": {
                            "node_name": node_name,
                            "attempts": attempt,
                        },
                    }
                logger.info(
                    "workflow_node_attempt_succeeded",
                    extra={"node_name": node_name, "attempt": attempt},
                )
                # 把人工输入（如有）和「清除暂停标记」合并回结果，返回给图
                if effective_state.get("human_input"):
                    result = {**result, "human_input": effective_state["human_input"]}
                if _should_pause_before(state.get("hitl_pause_before"), node_name):
                    result = {**result, "hitl_pause_before": ""}
                return result
            except asyncio.TimeoutError as exc:
                # 超时：包装成统一的 TimeoutError 记录下来，进入重试
                last_error = TimeoutError(f"{node_name} timed out after {timeout}s")
            except Exception as exc:
                # 其它任何异常：记录下来，进入重试
                last_error = exc

            # 记录这次尝试失败
            logger.warning(
                "workflow_node_attempt_failed",
                extra={
                    "node_name": node_name,
                    "attempt": attempt,
                    "attempts_allowed": attempts_allowed,
                    "error_type": type(last_error).__name__ if last_error else "",
                    "error_message": str(last_error)[:500] if last_error else "",
                },
            )
            # 如果还有重试次数且配置了退避，就按 attempt 倍数睡一会儿再试下一次
            if attempt < attempts_allowed and backoff:
                await asyncio.sleep(backoff * attempt)

        # ---- ④ 所有尝试都失败：算出总耗时并抛出最终异常 ----
        duration_ms = int((time.time() - started_at) * 1000)
        assert last_error is not None  # 能走到这里说明至少失败过一次，last_error 必然有值
        raise WorkflowNodeExecutionError(
            node_name,
            last_error,
            attempts=attempts_allowed,
            duration_ms=duration_ms,
        )

    return wrapped

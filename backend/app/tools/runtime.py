"""工具执行运行时（Tool Runtime）。

职责：
- 在"工具注册中心"之上提供一层执行保障：超时控制、失败重试、运行追踪快照；
- 每个节点的工具调用都走这里，统一获得：
    ① 超时：单次调用超过阈值（节点/harness 配置）即终止；
    ② 重试：失败按配置重试 N 次，带指数退避（sleep 逐渐加长）；
    ③ 追踪：每次调用的入参/出参摘要、耗时、错误码都记入 ToolRunSnapshot，
       供日志与前端状态展示；
- 工具的入参/出参不会原样落日志，统一经 _summarize 截断，避免敏感/超长内容刷屏。

设计取舍：工具执行是同步的（第三方 SDK 大多为同步），而 Agent 图是异步的——
因此用线程池把同步工具调用包成可超时等待的 future，再被 async 节点 await。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.logging import get_logger
from app.harness.registry import HarnessTool, get_harness_node
from app.tools.registry import ToolContext, ToolRegistry, ToolSpec, get_tool_registry


logger = get_logger("iris.tools.runtime")


@dataclass
class ToolRunSnapshot:
    """一次工具调用的运行快照（追踪 / 观测用，也用于前端展示）。

    tool_run_id: 本次调用的唯一 id（前端可按它关联日志）；
    status:      succeeded / failed；
    duration_ms: 总耗时（含重试）；
    input/output_summary: 截断后的入参/出参摘要；
    error_code / error_message: 失败原因（如 TOOL_TIMEOUT / TOOL_FAILED）。
    """

    tool_run_id: str
    tool_name: str
    status: str
    started_at: float
    finished_at: float
    duration_ms: int
    input_summary: str = ""
    output_summary: str = ""
    error_code: str = ""
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化 dict（写日志 / 传给前端）。"""
        return {
            "tool_run_id": self.tool_run_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


@dataclass
class ToolRuntimeResult:
    """工具执行结果：成功时带 value，失败时带快照（含错误信息）。"""

    ok: bool
    value: Any = None
    run: ToolRunSnapshot | None = None


class ToolRuntime:
    """同步工具执行器：超时 + 重试 + 追踪快照。"""

    def __init__(self, *, node_name: str, registry: ToolRegistry | None = None):
        self.node_name = node_name
        # 从 harness 清单加载当前节点允许的工具（名称 → HarnessTool 配置）
        self._tools = self._load_tools(node_name)
        self._registry = registry or get_tool_registry()

    def run_registered(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        state: dict[str, Any] | None = None,
        input_summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ToolRuntimeResult:
        """按注册名执行工具：先注入服务端权威参数，再自动补全工具元数据。

        执行顺序（顺序不能调换）：
          1. 取 ToolSpec；
          2. ★ 服务端注参：把 state 里的权威参数盖进 payload（S2）；
          3. 拼装追踪元数据（版本/描述/标签/出入参 schema）；
          4. 交给 run() 执行（超时 + 重试 + 快照）。
        """
        spec = self._registry.get(tool_name)
        # state 有两个用途，必须用同一份值：
        #   ① 服务端注参的数据源（第 2 步）
        #   ② 透传给 handler 的 ToolContext.state（第 4 步）
        # 若用两个不同的值，会出现"注参取自 A、handler 看到的却是 B"的诡异不一致。
        effective_state = state or {}

        # ★ S2：模型看不到 server_filled 字段，所以这里不是"防覆盖"而是"唯一来源"——
        # 即便模型（或上游调用方）硬塞了一个同名字段，也一律以 state 为准。
        effective_payload = self._apply_server_filled(spec, payload, effective_state)

        # 把工具定义信息拼进追踪元数据，日志里能看到"这次调用的是哪个版本、什么工具"
        effective_metadata = {
            "tool_version": spec.version,
            "tool_description": spec.description,
            "tool_tags": list(spec.tags),
            **(metadata or {}),
        }
        if spec.input_schema:
            effective_metadata.setdefault("input_schema", spec.input_schema)
        if spec.output_schema:
            effective_metadata.setdefault("output_schema", spec.output_schema)
        return self.run(
            tool_name,
            spec.handler,
            effective_payload,
            ToolContext(node_name=self.node_name, state=effective_state),
            # 用注入后的 payload 做摘要：日志要反映"实际执行时用的是什么参数"
            input_summary=input_summary or effective_payload,
            metadata=effective_metadata,
        )

    def _apply_server_filled(
        self,
        spec: ToolSpec,
        payload: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """把 ``spec.server_filled`` 声明的权威参数从 state 注入 payload（S2）。

        为什么需要这一步：
        像 ``knowledge_base_id`` 这种参数决定了"这次检索哪个知识库"，属于安全边界。
        它被排除在 params 模型之外（模型在 function schema 里根本看不到它），
        但"模型看不到"并不等于"服务端填得上" —— 必须有机制把真值补进去，
        否则 handler 只能拿到空值，一路退化到 ``kb_default``。

        两条行为约定：
        - **state 里有值就覆盖**（哪怕 payload 里已经有同名字段）：
          state 是权威来源，模型若硬塞一个假 id 也一律作废；
        - **state 里没有（或为 None）就什么都不做**：
          不凭空造值，也不删除 payload 里已有的字段 ——
          保持"未提供"和"显式传 None 之外的其它值"语义不变，
          免得破坏绕过 runtime 直接调 handler 的路径。
        """
        # 未声明服务端注入参数的工具：零开销直接返回原 payload
        if not spec.server_filled:
            return payload

        filled = dict(payload)  # 复制一份，不改动调用方传入的原对象
        for key in spec.server_filled:
            value = state.get(key)
            if value is not None:
                filled[key] = value
                logger.debug(
                    "工具 %s 的服务端注入参数已覆盖：%s（来源：图状态）",
                    spec.name,
                    key,
                )
        return filled

    def run(
        self,
        tool_name: str,
        func: Callable[..., Any],
        *args,
        input_summary: str = "",
        metadata: dict[str, Any] | None = None,
        **kwargs,
    ) -> ToolRuntimeResult:
        """执行任意可调用对象，带超时/重试/快照；供内部与测试复用。"""
        tool = self._tools.get(tool_name)
        # 超时与重试次数优先取 harness 里该工具的配置，缺省回退到节点级全局配置
        timeout = max(0.1, self._tool_timeout(tool))
        max_retries = max(0, self._tool_max_retries(tool))
        attempts_allowed = max_retries + 1  # 总尝试次数 = 重试次数 + 首次
        started_at = time.time()
        last_error: Exception | None = None

        # 重试循环：每次尝试都在独立线程里带超时执行
        for attempt in range(1, attempts_allowed + 1):
            try:
                logger.info(
                    "tool_attempt_started",
                    extra={
                        "node_name": self.node_name,
                        "tool_name": tool_name,
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "timeout_seconds": timeout,
                    },
                )
                value = self._run_with_timeout(func, timeout, *args, **kwargs)
                finished_at = time.time()
                base_metadata = metadata or {}
                snapshot = ToolRunSnapshot(
                    tool_run_id=f"tool_{uuid4().hex[:16]}",
                    tool_name=tool_name,
                    status="succeeded",
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=int((finished_at - started_at) * 1000),
                    input_summary=_summarize(input_summary),
                    output_summary=_summarize(value),
                    metadata={
                        **base_metadata,
                        "attempts": attempt,
                        "max_retries": max_retries,
                        "timeout_seconds": timeout,
                        "input_schema": (
                            tool.input_schema
                            if tool and tool.input_schema
                            else base_metadata.get("input_schema", "")
                        ),
                        "output_schema": (
                            tool.output_schema
                            if tool and tool.output_schema
                            else base_metadata.get("output_schema", "")
                        ),
                    },
                )
                logger.info(
                    "tool_attempt_succeeded",
                    extra={
                        "node_name": self.node_name,
                        "tool_name": tool_name,
                        "attempt": attempt,
                        "duration_ms": snapshot.duration_ms,
                    },
                )
                return ToolRuntimeResult(ok=True, value=value, run=snapshot)
            except FutureTimeoutError as exc:
                # 线程池超时：统一转成业务超时错误（记录原因为超时）
                last_error = TimeoutError(f"{tool_name} timed out after {timeout}s")
            except Exception as exc:
                last_error = exc

            logger.warning(
                "tool_attempt_failed",
                extra={
                    "node_name": self.node_name,
                    "tool_name": tool_name,
                    "attempt": attempt,
                    "attempts_allowed": attempts_allowed,
                    "error_type": type(last_error).__name__ if last_error else "",
                    "error_message": str(last_error)[:500] if last_error else "",
                },
            )
            # 重试间退避：sleep 时长随尝试次数递增（1 倍、2 倍...基础间隔）
            if attempt < attempts_allowed and settings.workflow_retry_backoff_seconds:
                time.sleep(max(0.0, settings.workflow_retry_backoff_seconds) * attempt)

        # 所有尝试都失败：构造失败快照（区分超时与其他错误码）
        finished_at = time.time()
        error_message = str(last_error) if last_error else "tool failed"
        error_code = "TOOL_TIMEOUT" if isinstance(last_error, TimeoutError) else "TOOL_FAILED"
        base_metadata = metadata or {}
        snapshot = ToolRunSnapshot(
            tool_run_id=f"tool_{uuid4().hex[:16]}",
            tool_name=tool_name,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=int((finished_at - started_at) * 1000),
            input_summary=_summarize(input_summary),
            output_summary="",
            error_code=error_code,
            error_message=error_message[:1000],
            metadata={
                **base_metadata,
                "attempts": attempts_allowed,
                "max_retries": max_retries,
                "timeout_seconds": timeout,
                "input_schema": (
                    tool.input_schema
                    if tool and tool.input_schema
                    else base_metadata.get("input_schema", "")
                ),
                "output_schema": (
                    tool.output_schema
                    if tool and tool.output_schema
                    else base_metadata.get("output_schema", "")
                ),
            },
        )
        return ToolRuntimeResult(ok=False, run=snapshot)

    def _run_with_timeout(
        self,
        func: Callable[..., Any],
        timeout: float,
        *args,
        **kwargs,
    ) -> Any:
        """在单线程线程池里执行函数并等待结果，超时则取消并抛超时异常。"""
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            future.cancel()
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _load_tools(self, node_name: str) -> dict[str, HarnessTool]:
        """从 harness 清单加载当前节点允许的工具配置；节点不存在则返回空集。"""
        try:
            node = get_harness_node(node_name)
        except Exception:
            return {}
        return {tool.name: tool for tool in node.tools if tool.name}

    def _tool_timeout(self, tool: HarnessTool | None) -> float:
        """单工具超时：工具级配置优先，缺省用节点级全局超时。"""
        if tool is not None and tool.timeout_seconds is not None:
            return tool.timeout_seconds
        return settings.workflow_node_timeout_seconds

    def _tool_max_retries(self, tool: HarnessTool | None) -> int:
        """单工具重试次数：工具级配置优先，缺省用节点级全局重试。"""
        if tool is not None and tool.max_retries is not None:
            return tool.max_retries
        return settings.workflow_node_max_retries


def _summarize(value: Any, max_len: int = 1000) -> str:
    """把工具入参/出参压成一段可读短文本（日志/快照用，避免超长内容刷屏）。

    规则：None → 空串；列表 → 展开前 10 项递归摘要；dict → 只列键名；
    其余 → 字符串化；最后统一压缩空白并截断到 max_len。
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        text = " ".join(_summarize(item, 200) for item in value[:10])
    elif isinstance(value, dict):
        text = str(sorted(value.keys()))
    else:
        text = str(value)
    return " ".join(text.split())[:max_len]

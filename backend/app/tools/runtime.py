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
from app.tools.registry import ToolContext, ToolRegistry, get_tool_registry


logger = get_logger("iris.tools.runtime")


@dataclass
class ToolRunSnapshot:
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
    ok: bool
    value: Any = None
    run: ToolRunSnapshot | None = None


class ToolRuntime:
    """Sync tool runner with timeout, retry, and trace snapshots."""

    def __init__(self, *, node_name: str, registry: ToolRegistry | None = None):
        self.node_name = node_name
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
        spec = self._registry.get(tool_name)
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
            payload,
            ToolContext(node_name=self.node_name, state=state or {}),
            input_summary=input_summary or payload,
            metadata=effective_metadata,
        )

    def run(
        self,
        tool_name: str,
        func: Callable[..., Any],
        *args,
        input_summary: str = "",
        metadata: dict[str, Any] | None = None,
        **kwargs,
    ) -> ToolRuntimeResult:
        tool = self._tools.get(tool_name)
        timeout = max(0.1, self._tool_timeout(tool))
        max_retries = max(0, self._tool_max_retries(tool))
        attempts_allowed = max_retries + 1
        started_at = time.time()
        last_error: Exception | None = None

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
            if attempt < attempts_allowed and settings.workflow_retry_backoff_seconds:
                time.sleep(max(0.0, settings.workflow_retry_backoff_seconds) * attempt)

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
        try:
            node = get_harness_node(node_name)
        except Exception:
            return {}
        return {tool.name: tool for tool in node.tools if tool.name}

    def _tool_timeout(self, tool: HarnessTool | None) -> float:
        if tool is not None and tool.timeout_seconds is not None:
            return tool.timeout_seconds
        return settings.workflow_node_timeout_seconds

    def _tool_max_retries(self, tool: HarnessTool | None) -> int:
        if tool is not None and tool.max_retries is not None:
            return tool.max_retries
        return settings.workflow_node_max_retries


def _summarize(value: Any, max_len: int = 1000) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        text = " ".join(_summarize(item, 200) for item in value[:10])
    elif isinstance(value, dict):
        text = str(sorted(value.keys()))
    else:
        text = str(value)
    return " ".join(text.split())[:max_len]

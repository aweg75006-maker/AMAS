from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.graph.state import AgentState
from app.harness.registry import get_harness_node
from langgraph.types import interrupt


logger = get_logger("iris.graph.runtime")


class WorkflowNodeExecutionError(Exception):
    """Raised after a workflow node exhausts timeout/retry policy."""

    def __init__(
        self,
        node_name: str,
        original: Exception,
        *,
        attempts: int,
        duration_ms: int,
    ):
        super().__init__(str(original))
        self.node_name = node_name
        self.original = original
        self.attempts = attempts
        self.duration_ms = duration_ms
        self.error_code = (
            "WORKFLOW_NODE_TIMEOUT"
            if isinstance(original, TimeoutError)
            else "WORKFLOW_NODE_FAILED"
        )


def wrap_node(
    node_name: str,
    fn: Callable[[AgentState], dict],
) -> Callable[[AgentState], object]:
    async def wrapped(
        state: AgentState,
        config: dict | None = None,
    ) -> dict:
        effective_state = dict(state)
        if effective_state.get("hitl_pause_before") == node_name:
            human_input = interrupt(
                {
                    "pause_node": node_name,
                    "prompt": f"工作流将在节点「{node_name}」执行前暂停，等待人工补充。",
                    "thread_id": (config or {}).get("configurable", {}).get("thread_id", ""),
                }
            )
            if isinstance(human_input, dict):
                human_input = human_input.get("human_input", "")
            effective_state["human_input"] = str(human_input or "").strip()
            effective_state["hitl_pause_before"] = ""
        try:
            harness_node = get_harness_node(node_name)
        except ConfigurationError:
            harness_node = None
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
        max_retries = max(0, configured_retries)
        attempts_allowed = max_retries + 1
        timeout = max(0.1, configured_timeout)
        backoff = max(0.0, settings.workflow_retry_backoff_seconds)
        started_at = time.time()
        last_error: Exception | None = None

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
                result = await asyncio.wait_for(
                    asyncio.to_thread(fn, effective_state),
                    timeout=timeout,
                )
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
                if effective_state.get("human_input"):
                    result = {**result, "human_input": effective_state["human_input"]}
                if state.get("hitl_pause_before") == node_name:
                    result = {**result, "hitl_pause_before": ""}
                return result
            except asyncio.TimeoutError as exc:
                last_error = TimeoutError(f"{node_name} timed out after {timeout}s")
            except Exception as exc:
                last_error = exc

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
            if attempt < attempts_allowed and backoff:
                await asyncio.sleep(backoff * attempt)

        duration_ms = int((time.time() - started_at) * 1000)
        assert last_error is not None
        raise WorkflowNodeExecutionError(
            node_name,
            last_error,
            attempts=attempts_allowed,
            duration_ms=duration_ms,
        )

    return wrapped

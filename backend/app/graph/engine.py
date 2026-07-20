from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.logging import get_logger
from app.graph.nodes.planner import plan_node
from app.graph.nodes.refiner import refine_node
from app.graph.nodes.researcher import research_node
from app.graph.nodes.reviewer import review_node
from app.graph.nodes.router import route_query
from app.graph.nodes.writer import write_node
from app.graph.policies.workflow_loop_policy import WorkflowLoopPolicy
from app.graph.runtime import wrap_node
from app.graph.state import AgentState
from app.harness.registry import get_harness_manifest


logger = get_logger("iris.graph.engine")


class WorkflowEngineExecutionError(Exception):
    """Raised when the workflow engine cannot safely continue a run."""

    error_code = "WORKFLOW_ENGINE_FAILED"

    def __init__(
        self,
        message: str,
        *,
        current_node: str = "",
        step_index: int = 0,
        elapsed_ms: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.current_node = current_node
        self.node_name = current_node
        self.step_index = step_index
        self.elapsed_ms = elapsed_ms
        self.details = details or {}


class WorkflowRunTimeoutError(WorkflowEngineExecutionError):
    error_code = "WORKFLOW_RUN_TIMEOUT"


class WorkflowMaxStepsExceededError(WorkflowEngineExecutionError):
    error_code = "WORKFLOW_MAX_STEPS_EXCEEDED"


class WorkflowRunCancelledError(WorkflowEngineExecutionError):
    error_code = "WORKFLOW_RUN_CANCELLED"


class WorkflowResumeError(WorkflowEngineExecutionError):
    """Raised when a run cannot be resumed (e.g. no checkpoint available)."""

    error_code = "WORKFLOW_RESUME_FAILED"


class WorkflowPausedError(WorkflowEngineExecutionError):
    """Raised when the workflow intentionally pauses for human-in-the-loop input.

    The caller should mark the run as PAUSED and wait for human input, then
    resume from the saved checkpoint (see :class:`PythonWorkflowEngine.astream`
    ``resume_thread_id``).
    """

    error_code = "WORKFLOW_PAUSED"


class PythonWorkflowEngine:
    """Primary workflow runner with explicit, testable Python control flow."""

    END = "__end__"

    def __init__(self) -> None:
        self.loop_policy = WorkflowLoopPolicy(
            max_revisions=get_harness_manifest().max_revisions
        )
        self.nodes: dict[str, Callable[[AgentState], Any]] = {
            "planner": wrap_node("planner", plan_node),
            "researcher": wrap_node("researcher", research_node),
            "writer": wrap_node("writer", write_node),
            "reviewer": wrap_node("reviewer", review_node),
            "refiner": wrap_node("refiner", refine_node),
        }

    async def astream(
        self,
        initial_state: AgentState,
        config: dict | None = None,
        *,
        resume_thread_id: str | None = None,
    ) -> AsyncIterator[dict[str, dict]]:
        state: AgentState = dict(initial_state)
        thread_id = (config or {}).get("configurable", {}).get("thread_id", "")

        if resume_thread_id:
            # 断点续跑：从最近一次 checkpoint 恢复执行位置与状态。
            checkpoint = await self._load_checkpoint(resume_thread_id)
            if checkpoint is None:
                raise WorkflowResumeError(
                    "no checkpoint available to resume",
                    current_node="__start__",
                    details={"thread_id": resume_thread_id},
                )
            restored = dict(checkpoint.get("state", {}))
            # 续跑会开启一个新的 workflow_run：调用方注入的运行标识
            # （run_id/request_id/user 等）应优先于旧 checkpoint，避免追踪错乱。
            for key in ("workflow_run_id", "request_id", "user_id", "username"):
                if key in initial_state:
                    restored[key] = initial_state[key]
            state = restored
            next_node = checkpoint["next_node"]
            pending_decision = checkpoint.get("pending_decision")
            steps = int(checkpoint.get("steps", 0))
            logger.info(
                "workflow_resume_from_checkpoint",
                extra={
                    "thread_id": resume_thread_id,
                    "next_node": next_node,
                    "steps": steps,
                },
            )
        else:
            next_node, entry_decision = self._route_entry(state)
            pending_decision = entry_decision
            steps = 0

        max_steps = self._max_steps()
        timeout_seconds = self._run_timeout_seconds()
        # 续跑时重置看门狗计时：以"恢复后的实际运行时间"重新约束超时。
        started_at = time.monotonic()

        while next_node != self.END:
            self._raise_if_run_timed_out(
                started_at,
                timeout_seconds,
                step_index=steps,
                current_node=next_node,
            )
            await self._raise_if_run_cancelled(
                state,
                step_index=steps,
                current_node=next_node,
                started_at=started_at,
            )
            steps += 1
            if steps > max_steps:
                elapsed_ms = self._elapsed_ms(started_at)
                raise WorkflowMaxStepsExceededError(
                    (
                        "workflow exceeded max steps "
                        f"(max_steps={max_steps}, elapsed_ms={elapsed_ms}, "
                        f"step_index={steps}, current_node={next_node})"
                    ),
                    current_node=next_node,
                    step_index=steps,
                    elapsed_ms=elapsed_ms,
                    details={
                        "max_steps": max_steps,
                        "elapsed_ms": elapsed_ms,
                        "step_index": steps,
                        "current_node": next_node,
                    },
                )

            node_name = next_node

            # ⭐ 断点续跑：在节点执行前持久化 checkpoint，
            # 即使该节点执行中崩溃，也可从本 checkpoint 重新执行该节点。
            if thread_id:
                await self._save_checkpoint(
                    state, node_name, steps, pending_decision, thread_id
                )

            # ⭐ HITL 人工介入：在执行指定节点前暂停，等待人工输入。
            # 断点已落盘，人工输入注入后可通过 resume_thread_id 从本节点续跑。
            hitl_pause_before = (config or {}).get("configurable", {}).get(
                "hitl_pause_before"
            )
            if hitl_pause_before and node_name == hitl_pause_before:
                raise WorkflowPausedError(
                    "workflow paused for human input",
                    current_node=node_name,
                    step_index=steps,
                    elapsed_ms=self._elapsed_ms(started_at),
                    details={
                        "pause_node": node_name,
                        "prompt": (
                            f"工作流已在节点「{node_name}」前暂停，"
                            "等待人工确认或补充指令后继续。"
                        ),
                    },
                )

            node_update = await self._run_node(node_name, state)
            await self._raise_if_run_cancelled(
                state,
                step_index=steps,
                current_node=node_name,
                started_at=started_at,
            )
            self._raise_if_run_timed_out(
                started_at,
                timeout_seconds,
                step_index=steps,
                current_node=node_name,
            )
            if pending_decision is not None:
                node_update = {
                    **node_update,
                    "_route_decisions": [pending_decision],
                }
            route_decisions = node_update.get("_route_decisions", [])
            node_update = {
                **node_update,
                "_workflow_event": self._event_snapshot(
                    node_name=node_name,
                    step_index=steps,
                    started_at=started_at,
                    config=config,
                    route_decisions=route_decisions,
                ),
            }
            state.update(node_update)
            yield {node_name: node_update}
            next_node, pending_decision = self._next_node(node_name, state)

    def _route_entry(self, state: AgentState) -> tuple[str, dict]:
        route = route_query(state)
        if route not in {"planner", "refiner"}:
            logger.warning("workflow_entry_route_invalid", extra={"route": route})
            return "planner", self._decision_snapshot(
                from_node="__start__",
                to_node="planner",
                reason="workflow_entry_route_invalid",
                metadata={"raw_route": route},
            )
        logger.info("workflow_entry_routed", extra={"next_node": route})
        return route, self._decision_snapshot(
            from_node="__start__",
            to_node=route,
            reason="workflow_entry_routed",
            metadata={"route": route},
        )

    async def _save_checkpoint(
        self,
        state: AgentState,
        next_node: str,
        steps: int,
        pending_decision: dict | None,
        thread_id: str,
    ) -> None:
        """Best-effort 持久化断点：在节点执行前保存完整状态与下一个要执行的节点。

        续跑时只需从这份 checkpoint 恢复 ``next_node`` 重新执行即可，
        无需重跑已完成的节点（已完成的节点结果已合并进 ``state``）。
        """
        try:
            from app.utils.redis_client import get_redis

            redis = await get_redis()
            payload = json.dumps(
                {
                    "state": state,
                    "next_node": next_node,
                    "steps": steps,
                    "pending_decision": pending_decision,
                },
                ensure_ascii=False,
                default=str,
            )
            await redis.save_checkpoint(thread_id, "main", payload)
        except Exception as exc:  # pragma: no cover - checkpoint 失败不应阻断主流程
            logger.warning(
                "workflow_checkpoint_save_failed",
                extra={"thread_id": thread_id, "error": str(exc)},
            )

    async def _load_checkpoint(self, thread_id: str) -> dict | None:
        """读取最近一次断点；不存在或读取失败时返回 ``None``。"""
        try:
            from app.utils.redis_client import get_redis

            redis = await get_redis()
            raw = await redis.get_checkpoint(thread_id, "main")
            if not raw:
                return None
            return json.loads(raw)
        except Exception as exc:  # pragma: no cover - 读取失败视为无可恢复断点
            logger.warning(
                "workflow_checkpoint_load_failed",
                extra={"thread_id": thread_id, "error": str(exc)},
            )
            return None

    async def _run_node(self, node_name: str, state: AgentState) -> dict:
        try:
            node = self.nodes[node_name]
        except KeyError as exc:
            raise RuntimeError(f"workflow node not registered: {node_name}") from exc
        result = await node(state)
        if not isinstance(result, dict):
            raise RuntimeError(f"workflow node returned non-dict: {node_name}")
        return result

    def _next_node(self, node_name: str, state: AgentState) -> tuple[str, dict | None]:
        if node_name == "planner":
            return "researcher", self._decision_snapshot(
                from_node="planner",
                to_node="researcher",
                reason="planner_completed",
            )
        if node_name == "researcher":
            decision = self.loop_policy.after_research(state)
            logger.info(decision.reason, extra=decision.metadata)
            return decision.next_node, self._decision_snapshot(
                from_node="researcher",
                to_node=decision.next_node,
                reason=decision.reason,
                metadata=decision.metadata,
            )
        if node_name == "writer":
            return "reviewer", self._decision_snapshot(
                from_node="writer",
                to_node="reviewer",
                reason="writer_completed",
            )
        if node_name == "reviewer":
            decision = self.loop_policy.after_review(state)
            if decision.reason == "review_max_revisions_reached":
                logger.warning(decision.reason, extra=decision.metadata)
            else:
                logger.info(decision.reason, extra=decision.metadata)
            return decision.next_node, self._decision_snapshot(
                from_node="reviewer",
                to_node=decision.next_node,
                reason=decision.reason,
                metadata=decision.metadata,
            )
        if node_name == "refiner":
            return self.END, self._decision_snapshot(
                from_node="refiner",
                to_node=self.END,
                reason="refiner_completed",
            )
        raise RuntimeError(f"workflow node has no outgoing route: {node_name}")

    def _max_steps(self) -> int:
        # Initial pass is planner/researcher/writer/reviewer. Each failed review can
        # add a replan path or a rewrite path. Keep a small buffer for refine flow.
        return 4 + get_harness_manifest().max_revisions * 4 + 2

    def _run_timeout_seconds(self) -> float:
        return max(0.001, settings.workflow_run_timeout_seconds)

    def _elapsed_ms(self, started_at: float) -> int:
        return int((time.monotonic() - started_at) * 1000)

    def _raise_if_run_timed_out(
        self,
        started_at: float,
        timeout_seconds: float,
        *,
        step_index: int,
        current_node: str,
    ) -> None:
        elapsed_ms = self._elapsed_ms(started_at)
        if elapsed_ms <= int(timeout_seconds * 1000):
            return
        raise WorkflowRunTimeoutError(
            (
                "workflow run timed out "
                f"(timeout_seconds={timeout_seconds}, elapsed_ms={elapsed_ms}, "
                f"step_index={step_index}, current_node={current_node})"
            ),
            current_node=current_node,
            step_index=step_index,
            elapsed_ms=elapsed_ms,
            details={
                "timeout_seconds": timeout_seconds,
                "elapsed_ms": elapsed_ms,
                "step_index": step_index,
                "current_node": current_node,
            },
        )

    async def _raise_if_run_cancelled(
        self,
        state: AgentState,
        *,
        step_index: int,
        current_node: str,
        started_at: float,
    ) -> None:
        run_id = str(state.get("workflow_run_id") or "")
        if not run_id:
            return
        from app.services.workflow_trace_service import get_workflow_trace_service

        trace_service = await get_workflow_trace_service()
        if not await trace_service.is_run_cancelled(run_id):
            return
        elapsed_ms = self._elapsed_ms(started_at)
        raise WorkflowRunCancelledError(
            (
                "workflow run cancelled "
                f"(run_id={run_id}, elapsed_ms={elapsed_ms}, "
                f"step_index={step_index}, current_node={current_node})"
            ),
            current_node=current_node,
            step_index=step_index,
            elapsed_ms=elapsed_ms,
            details={
                "run_id": run_id,
                "elapsed_ms": elapsed_ms,
                "step_index": step_index,
                "current_node": current_node,
            },
        )

    def _decision_snapshot(
        self,
        *,
        from_node: str,
        to_node: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "decision_id": f"route_{uuid4().hex[:16]}",
            "from_node": from_node,
            "to_node": to_node,
            "reason": reason,
            "created_at": time.time(),
            "metadata": {
                "engine": "python",
                **(metadata or {}),
            },
        }

    def _event_snapshot(
        self,
        *,
        node_name: str,
        step_index: int,
        started_at: float,
        config: dict | None,
        route_decisions: list[dict],
    ) -> dict[str, Any]:
        configurable = (config or {}).get("configurable") or {}
        return {
            "engine": "python",
            "node_name": node_name,
            "step_index": step_index,
            "run_elapsed_ms": self._elapsed_ms(started_at),
            "route_decisions": route_decisions,
            "thread_id": configurable.get("thread_id", ""),
            "session_id": configurable.get("session_id", ""),
        }


def create_python_workflow_engine() -> PythonWorkflowEngine:
    return PythonWorkflowEngine()

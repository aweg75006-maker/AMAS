from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

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


NodeFn = Callable[[AgentState], dict]


class PythonWorkflowEngine:
    """Pure Python workflow runner compatible with LangGraph's event shape."""

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
    ) -> AsyncIterator[dict[str, dict]]:
        state: AgentState = dict(initial_state)
        next_node = self._route_entry(state)
        max_steps = self._max_steps()
        steps = 0

        while next_node != self.END:
            steps += 1
            if steps > max_steps:
                raise RuntimeError(f"workflow exceeded max steps: {max_steps}")

            node_name = next_node
            node_update = await self._run_node(node_name, state)
            state.update(node_update)
            yield {node_name: node_update}
            next_node = self._next_node(node_name, state)

    def _route_entry(self, state: AgentState) -> str:
        route = route_query(state)
        if route not in {"planner", "refiner"}:
            logger.warning("workflow_entry_route_invalid", extra={"route": route})
            return "planner"
        logger.info("workflow_entry_routed", extra={"next_node": route})
        return route

    async def _run_node(self, node_name: str, state: AgentState) -> dict:
        try:
            node = self.nodes[node_name]
        except KeyError as exc:
            raise RuntimeError(f"workflow node not registered: {node_name}") from exc
        result = await node(state)
        if not isinstance(result, dict):
            raise RuntimeError(f"workflow node returned non-dict: {node_name}")
        return result

    def _next_node(self, node_name: str, state: AgentState) -> str:
        if node_name == "planner":
            return "researcher"
        if node_name == "researcher":
            decision = self.loop_policy.after_research(state)
            logger.info(decision.reason, extra=decision.metadata)
            return decision.next_node
        if node_name == "writer":
            return "reviewer"
        if node_name == "reviewer":
            decision = self.loop_policy.after_review(state)
            if decision.reason == "review_max_revisions_reached":
                logger.warning(decision.reason, extra=decision.metadata)
            else:
                logger.info(decision.reason, extra=decision.metadata)
            return decision.next_node
        if node_name == "refiner":
            return self.END
        raise RuntimeError(f"workflow node has no outgoing route: {node_name}")

    def _max_steps(self) -> int:
        # Initial pass is planner/researcher/writer/reviewer. Each failed review can
        # add a replan path or a rewrite path. Keep a small buffer for refine flow.
        return 4 + get_harness_manifest().max_revisions * 4 + 2


def create_python_workflow_engine() -> PythonWorkflowEngine:
    return PythonWorkflowEngine()

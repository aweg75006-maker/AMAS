import pytest

from app.graph import engine as python_engine_module
from app.graph.engine import PythonWorkflowEngine

pytestmark = pytest.mark.legacy_langgraph


async def _collect_python_steps(state):
    engine = PythonWorkflowEngine()
    steps = []
    async for event in engine.astream(dict(state), config={"configurable": {"thread_id": "t1"}}):
        steps.extend(event.keys())
    return steps


async def _collect_legacy_langgraph_steps(state):
    from app.graph import graph as legacy_langgraph_module

    graph = legacy_langgraph_module.create_graph()
    steps = []
    async for event in graph.astream(
        dict(state),
        config={"configurable": {"thread_id": "t1"}},
    ):
        steps.extend(event.keys())
    return steps


async def _collect_python_steps_with_patch(monkeypatch, state, **patch_kwargs):
    _patch_both_engines(monkeypatch, **patch_kwargs)
    return await _collect_python_steps(state)


async def _collect_legacy_langgraph_steps_with_patch(monkeypatch, state, **patch_kwargs):
    _patch_both_engines(monkeypatch, **patch_kwargs)
    return await _collect_legacy_langgraph_steps(state)


def _patch_both_engines(monkeypatch, *, route="planner", review_sequence=None):
    from app.graph import graph as legacy_langgraph_module

    review_sequence = list(review_sequence or [("PASS", "none", "")])
    review_calls = {"count": 0}

    def route_query(state):
        return route

    def plan_node(state):
        return {"plan": ["topic"]}

    def research_node(state):
        return {"search_results": ["evidence"]}

    def write_node(state):
        return {"final_report": f"report:{state.get('revision_number', 0)}"}

    def review_node(state):
        index = min(review_calls["count"], len(review_sequence) - 1)
        status, action, critique = review_sequence[index]
        review_calls["count"] += 1
        return {
            "review_status": status,
            "review_action": action,
            "revision_number": state.get("revision_number", 0) + 1,
            "critique": critique,
        }

    def refine_node(state):
        return {"final_report": "refined", "review_status": "PASS"}

    for module in (python_engine_module, legacy_langgraph_module):
        monkeypatch.setattr(module, "route_query", route_query)
        monkeypatch.setattr(module, "plan_node", plan_node)
        monkeypatch.setattr(module, "research_node", research_node)
        monkeypatch.setattr(module, "write_node", write_node)
        monkeypatch.setattr(module, "review_node", review_node)
        monkeypatch.setattr(module, "refine_node", refine_node)


@pytest.mark.asyncio
async def test_legacy_langgraph_matches_python_engine_happy_path(monkeypatch):
    state = {"query": "hello", "search_mode": "hybrid", "revision_number": 0}

    assert await _collect_python_steps_with_patch(
        monkeypatch, state
    ) == await _collect_legacy_langgraph_steps_with_patch(monkeypatch, state)


@pytest.mark.asyncio
async def test_legacy_langgraph_matches_python_engine_rewrite_loop(monkeypatch):
    state = {"query": "hello", "search_mode": "hybrid", "revision_number": 0}
    patch_kwargs = {
        "review_sequence": [
            ("FAIL", "rewrite", "rewrite structure"),
            ("PASS", "none", ""),
        ]
    }

    assert await _collect_python_steps_with_patch(
        monkeypatch, state, **patch_kwargs
    ) == await _collect_legacy_langgraph_steps_with_patch(monkeypatch, state, **patch_kwargs)


@pytest.mark.asyncio
async def test_legacy_langgraph_matches_python_engine_refine_path(monkeypatch):
    state = {"query": "改详细一点", "final_report": "old"}

    assert await _collect_python_steps_with_patch(
        monkeypatch, state, route="refiner"
    ) == await _collect_legacy_langgraph_steps_with_patch(monkeypatch, state, route="refiner")

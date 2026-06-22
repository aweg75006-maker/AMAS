import pytest

from app.graph import engine as engine_module
from app.graph.engine import (
    PythonWorkflowEngine,
    WorkflowMaxStepsExceededError,
    WorkflowRunTimeoutError,
)


async def _collect_events(engine, state):
    events = []
    async for event in engine.astream(state, config={"configurable": {"thread_id": "t1"}}):
        events.append(event)
    return events


def _patch_nodes(monkeypatch, *, review_action="none", review_status="PASS"):
    monkeypatch.setattr(engine_module, "route_query", lambda state: "planner")
    monkeypatch.setattr(engine_module, "plan_node", lambda state: {"plan": ["topic"]})
    monkeypatch.setattr(
        engine_module,
        "research_node",
        lambda state: {"search_results": ["evidence"]},
    )
    monkeypatch.setattr(
        engine_module,
        "write_node",
        lambda state: {
            "final_report": f"report:{state.get('revision_number', 0)}",
        },
    )
    monkeypatch.setattr(
        engine_module,
        "review_node",
        lambda state: {
            "review_status": review_status,
            "review_action": review_action,
            "revision_number": state.get("revision_number", 0) + 1,
            "critique": "" if review_status == "PASS" else "please improve",
        },
    )


@pytest.mark.asyncio
async def test_python_workflow_engine_runs_happy_path(monkeypatch):
    _patch_nodes(monkeypatch)
    engine = PythonWorkflowEngine()

    events = await _collect_events(
        engine,
        {"query": "hello", "search_mode": "hybrid", "revision_number": 0},
    )

    assert [list(event)[0] for event in events] == [
        "planner",
        "researcher",
        "writer",
        "reviewer",
    ]
    assert events[0]["planner"]["_route_decisions"][0]["from_node"] == "__start__"
    assert events[1]["researcher"]["_route_decisions"][0]["from_node"] == "planner"
    assert events[-1]["reviewer"]["_route_decisions"][0]["to_node"] == "reviewer"


@pytest.mark.asyncio
async def test_python_workflow_engine_routes_rewrite_to_writer(monkeypatch):
    calls = {"review": 0}
    monkeypatch.setattr(engine_module, "route_query", lambda state: "planner")
    monkeypatch.setattr(engine_module, "plan_node", lambda state: {"plan": ["topic"]})
    monkeypatch.setattr(
        engine_module,
        "research_node",
        lambda state: {"search_results": ["evidence"]},
    )
    monkeypatch.setattr(engine_module, "write_node", lambda state: {"final_report": "report"})

    def review_node(state):
        calls["review"] += 1
        if calls["review"] == 1:
            return {
                "review_status": "FAIL",
                "review_action": "rewrite",
                "revision_number": 1,
                "critique": "rewrite structure",
            }
        return {
            "review_status": "PASS",
            "review_action": "none",
            "revision_number": 2,
            "critique": "",
        }

    monkeypatch.setattr(engine_module, "review_node", review_node)
    engine = PythonWorkflowEngine()

    events = await _collect_events(
        engine,
        {"query": "hello", "search_mode": "hybrid", "revision_number": 0},
    )

    assert [list(event)[0] for event in events] == [
        "planner",
        "researcher",
        "writer",
        "reviewer",
        "writer",
        "reviewer",
    ]
    assert events[4]["writer"]["_route_decisions"][0]["reason"] == (
        "review_failed_routing_to_writer"
    )


@pytest.mark.asyncio
async def test_python_workflow_engine_refine_path(monkeypatch):
    monkeypatch.setattr(engine_module, "route_query", lambda state: "refiner")
    monkeypatch.setattr(
        engine_module,
        "refine_node",
        lambda state: {"final_report": "refined", "review_status": "PASS"},
    )
    engine = PythonWorkflowEngine()

    events = await _collect_events(
        engine,
        {"query": "改详细一点", "final_report": "old"},
    )

    assert [list(event)[0] for event in events] == ["refiner"]
    assert events[0]["refiner"]["final_report"] == "refined"
    assert events[0]["refiner"]["_route_decisions"][0]["to_node"] == "refiner"


@pytest.mark.asyncio
async def test_python_workflow_engine_raises_run_timeout(monkeypatch):
    from app.core.config import settings

    _patch_nodes(monkeypatch)
    monkeypatch.setattr(settings, "workflow_run_timeout_seconds", 0.001)
    engine = PythonWorkflowEngine()
    monkeypatch.setattr(engine, "_elapsed_ms", lambda started_at: 10)

    with pytest.raises(WorkflowRunTimeoutError) as exc:
        await _collect_events(
            engine,
            {"query": "hello", "search_mode": "hybrid", "revision_number": 0},
        )

    assert exc.value.error_code == "WORKFLOW_RUN_TIMEOUT"
    assert exc.value.current_node == "planner"
    assert exc.value.details["timeout_seconds"] == 0.001


@pytest.mark.asyncio
async def test_python_workflow_engine_raises_max_steps_exceeded(monkeypatch):
    _patch_nodes(monkeypatch, review_action="rewrite", review_status="FAIL")
    engine = PythonWorkflowEngine()
    monkeypatch.setattr(engine, "_max_steps", lambda: 1)

    with pytest.raises(WorkflowMaxStepsExceededError) as exc:
        await _collect_events(
            engine,
            {"query": "hello", "search_mode": "hybrid", "revision_number": 0},
        )

    assert exc.value.error_code == "WORKFLOW_MAX_STEPS_EXCEEDED"
    assert exc.value.current_node == "researcher"
    assert exc.value.details["max_steps"] == 1

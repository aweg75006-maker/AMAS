import pytest

from app.api import routes_chat
from app.core.identity import RequestContext
from app.graph.engine import WorkflowRunCancelledError, WorkflowRunTimeoutError
from app.models.domain import WorkflowRunStatus


class FakeWorkflowEngine:
    async def astream(self, initial_state, config=None, *, resume_thread_id=None):
        yield {"planner": {"plan": ["fake"]}}


class FakeTraceService:
    def __init__(self):
        self.node_failures = []
        self.finished_runs = []
        self.error_events = []

    async def record_node_failure(self, **kwargs):
        self.node_failures.append(kwargs)

    async def finish_run(self, *args, **kwargs):
        self.finished_runs.append((args, kwargs))

    async def record_error_event(self, **kwargs):
        self.error_events.append(kwargs)


@pytest.mark.asyncio
async def test_chat_stream_uses_configured_workflow_engine(monkeypatch):
    monkeypatch.setattr(
        routes_chat,
        "create_workflow_engine",
        lambda: FakeWorkflowEngine(),
    )

    events = []
    async for event in routes_chat._stream_workflow_events(
        {"query": "hello"},
        {"configurable": {"thread_id": "t1"}},
    ):
        events.append(event)

    assert events == [{"planner": {"plan": ["fake"]}}]


def test_public_state_update_hides_workflow_event():
    public = routes_chat._public_state_update(
        {
            "plan": ["fake"],
            "_workflow_event": {"engine": "python"},
            "_route_decisions": [{"from_node": "__start__"}],
        }
    )

    assert public == {"plan": ["fake"]}


def test_workflow_failure_snapshot_normalizes_engine_errors(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "workflow_engine", "langgraph")
    monkeypatch.setattr(settings, "workflow_run_timeout_seconds", 300)

    snapshot = routes_chat._workflow_failure_snapshot(
        WorkflowRunTimeoutError(
            "workflow run timed out",
            current_node="planner",
            step_index=2,
            elapsed_ms=301000,
            details={"timeout_seconds": 300},
        )
    )

    assert snapshot["error_code"] == "WORKFLOW_RUN_TIMEOUT"
    assert snapshot["node_name"] == "planner"
    assert snapshot["duration_ms"] == 301000
    assert snapshot["details"]["engine"] == "langgraph"
    assert snapshot["details"]["workflow_run_timeout_seconds"] == 300
    assert snapshot["details"]["step_index"] == 2


@pytest.mark.asyncio
async def test_record_workflow_failure_marks_run_failed_and_records_error():
    trace_service = FakeTraceService()
    workflow_run = type("WorkflowRun", (), {"run_id": "run_1"})()
    context = RequestContext(
        tenant_id="tenant_1",
        user_id="user_1",
        username="tester",
        role="owner",
        auth_source="jwt",
    )
    exc = WorkflowRunTimeoutError(
        "workflow run timed out",
        current_node="planner",
        step_index=1,
        elapsed_ms=301000,
        details={"timeout_seconds": 300, "elapsed_ms": 301000},
    )
    failure = routes_chat._workflow_failure_snapshot(exc)

    run_finished = await routes_chat._record_workflow_failure(
        trace_service=trace_service,
        workflow_run=workflow_run,
        context=context,
        request_id="req_1",
        session_id="session_1",
        turn_id="turn_1",
        path="/api/chat",
        exc=exc,
        failure=failure,
        run_finished=False,
    )

    assert run_finished is True
    assert trace_service.node_failures[0]["node_name"] == "planner"
    assert trace_service.node_failures[0]["error_code"] == "WORKFLOW_RUN_TIMEOUT"
    assert trace_service.finished_runs[0][1]["status"] == WorkflowRunStatus.FAILED.value
    assert trace_service.finished_runs[0][1]["error_code"] == "WORKFLOW_RUN_TIMEOUT"
    assert trace_service.error_events[0]["error_code"] == "WORKFLOW_RUN_TIMEOUT"
    assert trace_service.error_events[0]["details"]["elapsed_ms"] == 301000


@pytest.mark.asyncio
async def test_record_workflow_failure_preserves_cancelled_run_status():
    trace_service = FakeTraceService()
    workflow_run = type("WorkflowRun", (), {"run_id": "run_1"})()
    context = RequestContext(
        tenant_id="tenant_1",
        user_id="user_1",
        username="tester",
        role="owner",
        auth_source="jwt",
    )
    exc = WorkflowRunCancelledError(
        "workflow run cancelled",
        current_node="planner",
        step_index=1,
        elapsed_ms=1000,
        details={"run_id": "run_1"},
    )
    failure = routes_chat._workflow_failure_snapshot(exc)

    run_finished = await routes_chat._record_workflow_failure(
        trace_service=trace_service,
        workflow_run=workflow_run,
        context=context,
        request_id="req_1",
        session_id="session_1",
        turn_id="turn_1",
        path="/api/chat",
        exc=exc,
        failure=failure,
        run_finished=False,
    )

    assert run_finished is False
    assert trace_service.finished_runs == []
    assert trace_service.error_events[0]["error_code"] == "WORKFLOW_RUN_CANCELLED"

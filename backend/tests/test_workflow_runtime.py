import time

import pytest

from app.graph.runtime import WorkflowNodeExecutionError, wrap_node


@pytest.mark.asyncio
async def test_wrap_node_retries_then_succeeds(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "workflow_node_timeout_seconds", 1)
    monkeypatch.setattr(settings, "workflow_node_max_retries", 1)
    monkeypatch.setattr(settings, "workflow_retry_backoff_seconds", 0)
    calls = {"count": 0}

    def flaky_node(_state):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary")
        return {"final_report": "ok"}

    wrapped = wrap_node("writer", flaky_node)
    result = await wrapped({"query": "hello"})

    assert result["final_report"] == "ok"
    assert result["_workflow_retry"]["attempts"] == 2


@pytest.mark.asyncio
async def test_wrap_node_raises_after_timeout(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "workflow_node_timeout_seconds", 0.01)
    monkeypatch.setattr(settings, "workflow_node_max_retries", 0)
    monkeypatch.setattr(settings, "workflow_retry_backoff_seconds", 0)

    def slow_node(_state):
        time.sleep(0.2)
        return {"final_report": "late"}

    wrapped = wrap_node("writer", slow_node)

    with pytest.raises(WorkflowNodeExecutionError) as exc:
        await wrapped({"query": "hello"})

    assert exc.value.node_name == "writer"
    assert exc.value.error_code == "WORKFLOW_NODE_TIMEOUT"
    assert exc.value.attempts == 1

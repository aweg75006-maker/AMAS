import time

from app.tools.runtime import ToolRuntime


def test_tool_runtime_records_success():
    runtime = ToolRuntime(node_name="researcher")

    result = runtime.run(
        "web.search",
        lambda query: f"result for {query}",
        "hello",
        input_summary="hello",
        metadata={"kind": "unit"},
    )

    assert result.ok is True
    assert result.value == "result for hello"
    assert result.run is not None
    assert result.run.status == "succeeded"
    assert result.run.tool_name == "web.search"
    assert result.run.metadata["kind"] == "unit"


def test_tool_runtime_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.tools.runtime.settings.workflow_retry_backoff_seconds", 0)
    runtime = ToolRuntime(node_name="researcher")
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary")
        return "ok"

    result = runtime.run("rag.retrieve", flaky)

    assert result.ok is True
    assert result.value == "ok"
    assert calls["count"] == 2
    assert result.run.metadata["attempts"] == 2


def test_tool_runtime_records_failure_after_retries(monkeypatch):
    monkeypatch.setattr("app.tools.runtime.settings.workflow_retry_backoff_seconds", 0)
    runtime = ToolRuntime(node_name="researcher")

    result = runtime.run("rag.retrieve", lambda: (_ for _ in ()).throw(ValueError("boom")))

    assert result.ok is False
    assert result.run is not None
    assert result.run.status == "failed"
    assert result.run.error_code == "TOOL_FAILED"
    assert "boom" in result.run.error_message


def test_tool_runtime_records_timeout(monkeypatch):
    monkeypatch.setattr("app.tools.runtime.settings.workflow_retry_backoff_seconds", 0)
    monkeypatch.setattr("app.tools.runtime.settings.workflow_node_timeout_seconds", 0.05)
    runtime = ToolRuntime(node_name="researcher")

    result = runtime.run(
        "unknown.slow_tool",
        lambda: time.sleep(0.2),
        metadata={"timeout_probe": True},
    )

    assert result.ok is False
    assert result.run is not None
    assert result.run.error_code == "TOOL_TIMEOUT"
    assert result.run.metadata["timeout_probe"] is True

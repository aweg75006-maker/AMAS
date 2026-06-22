from app.services.workflow_runtime_service import (
    workflow_runtime_diagnostics,
    workflow_runtime_fingerprint,
)


def test_workflow_runtime_fingerprint_contains_versions_and_policy():
    runtime = workflow_runtime_fingerprint()

    assert runtime["workflow_version"]
    assert runtime["prompt_version"]
    assert runtime["node_policy_version"]
    assert runtime["workflow_engine"] in {"langgraph", "python"}
    assert runtime["harness"]["workflow_id"] == "research_report"
    assert runtime["harness"]["nodes"]["planner"]["prompt_id"] == "planner.research.v1"
    assert runtime["loop_policy"]["max_revisions"] == 3
    assert runtime["loop_policy"]["review_fail_next"] == "planner"
    assert runtime["loop_policy"]["review_rewrite_next"] == "writer"
    assert runtime["models"]["fast"]
    assert runtime["node_execution"]["timeout_seconds"] > 0


def test_workflow_runtime_diagnostics_contains_rollout_status_and_tools():
    diagnostics = workflow_runtime_diagnostics()

    assert diagnostics["diagnostics"]["active_engine"] in {"langgraph", "python"}
    assert diagnostics["diagnostics"]["primary_engine"] == "python"
    assert diagnostics["diagnostics"]["legacy_fallback_engine"] == "langgraph"
    assert diagnostics["diagnostics"]["available_engines"] == ["python", "langgraph"]
    assert diagnostics["diagnostics"]["rollback_engine"] == "langgraph"
    assert diagnostics["diagnostics"]["tool_trace_enabled"] is True
    assert diagnostics["diagnostics"]["node_trace_enabled"] is True
    tool_names = {tool["name"] for tool in diagnostics["registered_tools"]}
    assert {"rag.retrieve", "rag.relevance_grade", "web.search"} <= tool_names

from app.services.workflow_runtime_service import (
    workflow_runtime_diagnostics,
    workflow_runtime_fingerprint,
)


def test_workflow_runtime_fingerprint_contains_versions_and_policy():
    runtime = workflow_runtime_fingerprint()

    assert runtime["workflow_version"]
    assert runtime["prompt_version"]
    assert runtime["node_policy_version"]
    assert runtime["workflow_engine"] == "langgraph"
    assert runtime["primary_engine"] == "langgraph"
    assert runtime["harness"]["workflow_id"] == "research_report"
    assert runtime["harness"]["nodes"]["planner"]["prompt_id"] == "planner.research.v1"
    assert runtime["loop_policy"]["max_revisions"] == 3
    assert runtime["loop_policy"]["review_fail_next"] == "planner"
    assert runtime["loop_policy"]["review_rewrite_next"] == "writer"
    assert runtime["models"]["fast"]
    assert runtime["node_execution"]["timeout_seconds"] > 0
    assert runtime["run_execution"]["timeout_seconds"] == 300


def test_workflow_runtime_diagnostics_contains_rollout_status_and_tools():
    diagnostics = workflow_runtime_diagnostics()

    assert diagnostics["diagnostics"]["active_engine"] == "langgraph"
    assert diagnostics["diagnostics"]["primary_engine"] == "langgraph"
    assert diagnostics["diagnostics"]["production_recommended"] is True
    assert diagnostics["diagnostics"]["warnings"] == []
    assert diagnostics["diagnostics"]["available_engines"] == ["langgraph"]
    assert diagnostics["diagnostics"]["rollback_engine"] is None
    assert diagnostics["diagnostics"]["tool_trace_enabled"] is True
    assert diagnostics["diagnostics"]["node_trace_enabled"] is True
    tool_names = {tool["name"] for tool in diagnostics["registered_tools"]}
    assert {"rag.retrieve", "rag.relevance_grade", "web.search"} <= tool_names

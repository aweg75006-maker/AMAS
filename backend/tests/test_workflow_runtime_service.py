from app.services.workflow_runtime_service import workflow_runtime_fingerprint


def test_workflow_runtime_fingerprint_contains_versions_and_policy():
    runtime = workflow_runtime_fingerprint()

    assert runtime["workflow_version"]
    assert runtime["prompt_version"]
    assert runtime["node_policy_version"]
    assert runtime["harness"]["workflow_id"] == "research_report"
    assert runtime["harness"]["nodes"]["planner"]["prompt_id"] == "planner.research.v1"
    assert runtime["models"]["fast"]
    assert runtime["node_execution"]["timeout_seconds"] > 0

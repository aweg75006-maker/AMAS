from app.harness.registry import (
    get_harness_manifest,
    get_harness_node,
    get_prompt_template,
    harness_fingerprint,
)


def test_default_harness_manifest_maps_current_business_flow():
    manifest = get_harness_manifest()

    assert manifest.workflow_id == "research_report"
    assert set(manifest.nodes) >= {
        "planner",
        "researcher",
        "writer",
        "reviewer",
        "refiner",
    }
    assert manifest.nodes["planner"].prompt_id == "planner.research.v1"
    assert manifest.max_revisions == 3
    researcher_tools = {tool.name: tool for tool in manifest.nodes["researcher"].tools}
    assert "web.search" in researcher_tools
    assert researcher_tools["web.search"].timeout_seconds == 45


def test_prompt_template_can_render_planner_prompt():
    node = get_harness_node("planner")
    prompt = get_prompt_template(node.prompt_id).format(
        query="测试问题",
        critique="",
        memory_context="无历史",
    )

    assert "测试问题" in prompt
    assert "只返回关键词" in prompt


def test_harness_fingerprint_contains_node_prompt_ids():
    fingerprint = harness_fingerprint()

    assert fingerprint["workflow_id"] == "research_report"
    assert fingerprint["max_revisions"] == 3
    assert fingerprint["nodes"]["writer"]["prompt_id"] == "writer.report.v1"

from dataclasses import dataclass

from app.graph.nodes.researcher import research_node
from app.tools.registry import ToolRegistry, ToolSpec, reset_tool_registry_for_tests


@dataclass
class FakeDoc:
    page_content: str


def test_researcher_uses_registered_tools():
    registry = ToolRegistry()
    calls = []
    registry.register(
        ToolSpec(
            name="rag.retrieve",
            handler=lambda payload, context: calls.append(("rag.retrieve", payload)) or [
                FakeDoc("本地资料：IRIS 支持工具注册。")
            ],
        )
    )
    registry.register(
        ToolSpec(
            name="rag.relevance_grade",
            handler=lambda payload, context: calls.append(("rag.relevance_grade", payload)) or "YES",
        )
    )
    registry.register(
        ToolSpec(
            name="web.search",
            handler=lambda payload, context: calls.append(("web.search", payload)) or "网络资料",
        )
    )

    reset_tool_registry_for_tests(registry)
    try:
        result = research_node(
            {
                "query": "IRIS 工具注册是什么",
                "plan": ["IRIS Tool Registry"],
                "search_mode": "hybrid",
                "knowledge_base_id": "kb_test",
            }
        )
    finally:
        reset_tool_registry_for_tests(None)

    assert result["search_results"][0].startswith("### 📂 本地文档资料")
    assert result["search_results"][1].startswith("### 🌐 网络搜索结果")
    assert [name for name, _payload in calls] == [
        "rag.retrieve",
        "rag.relevance_grade",
        "web.search",
    ]
    assert result["_tool_runs"][0]["tool_name"] == "rag.retrieve"

import pytest

from app.core.exceptions import ConfigurationError
from app.tools.registry import (
    ToolRegistry,
    ToolSpec,
    get_tool_registry,
    reset_tool_registry_for_tests,
)
from app.tools.runtime import ToolRuntime


def test_default_tool_registry_contains_research_tools():
    registry = get_tool_registry()
    names = {spec.name for spec in registry.list_specs()}

    assert {"rag.retrieve", "rag.relevance_grade", "web.search"} <= names
    assert registry.get("web.search").input_schema == "query:string"


def test_tool_registry_rejects_duplicate_names():
    registry = ToolRegistry()
    spec = ToolSpec(name="unit.tool", handler=lambda payload, context: payload)
    registry.register(spec)

    with pytest.raises(ConfigurationError):
        registry.register(spec)


def test_tool_runtime_runs_registered_handler():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="unit.echo",
            handler=lambda payload, context: {
                "value": payload["value"],
                "node": context.node_name,
                "state": context.state.get("query"),
            },
            input_schema="value:string",
            output_schema="value:string, node:string",
            tags=("unit",),
        )
    )
    runtime = ToolRuntime(node_name="researcher", registry=registry)

    result = runtime.run_registered(
        "unit.echo",
        {"value": "hello"},
        state={"query": "question"},
    )

    assert result.ok is True
    assert result.value == {
        "value": "hello",
        "node": "researcher",
        "state": "question",
    }
    assert result.run is not None
    assert result.run.metadata["input_schema"] == "value:string"
    assert result.run.metadata["output_schema"] == "value:string, node:string"
    assert result.run.metadata["tool_tags"] == ["unit"]


def test_tool_registry_can_be_reset_for_tests():
    registry = ToolRegistry()
    registry.register(ToolSpec(name="unit.one", handler=lambda payload, context: "ok"))

    reset_tool_registry_for_tests(registry)
    try:
        assert get_tool_registry().has("unit.one")
    finally:
        reset_tool_registry_for_tests(None)

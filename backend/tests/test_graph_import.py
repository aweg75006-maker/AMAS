import pytest


def test_langgraph_graph_compiles_without_eager_external_clients():
    from app.graph.graph import create_graph

    graph = create_graph()

    assert graph is not None
    assert type(graph).__name__ == "CompiledStateGraph"


def test_create_workflow_engine_uses_langgraph():
    from app.graph.engine_factory import create_workflow_engine

    engine = create_workflow_engine()

    assert type(engine).__name__ == "LangGraphWorkflowEngineAdapter"

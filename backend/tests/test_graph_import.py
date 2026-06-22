def test_legacy_langgraph_graph_compiles_without_eager_external_clients():
    from app.graph.graph import create_graph

    graph = create_graph()

    assert graph is not None
    assert type(graph).__name__ == "CompiledStateGraph"


def test_create_python_workflow_engine_without_eager_external_clients():
    from app.graph.engine import create_python_workflow_engine

    engine = create_python_workflow_engine()

    assert engine is not None
    assert type(engine).__name__ == "PythonWorkflowEngine"


def test_create_workflow_engine_uses_configured_engine(monkeypatch):
    from app.core.config import settings
    from app.graph.engine_factory import create_workflow_engine

    monkeypatch.setattr(settings, "workflow_engine", "python")
    python_engine = create_workflow_engine()
    assert type(python_engine).__name__ == "PythonWorkflowEngine"

    monkeypatch.setattr(settings, "workflow_engine", "langgraph")
    langgraph_engine = create_workflow_engine()
    assert type(langgraph_engine).__name__ == "LangGraphWorkflowEngineAdapter"

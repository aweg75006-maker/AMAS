def test_create_graph_compiles_without_eager_external_clients():
    from app.graph.graph import create_graph

    graph = create_graph()

    assert graph is not None
    assert type(graph).__name__ == "CompiledStateGraph"


def test_create_python_workflow_engine_without_eager_external_clients():
    from app.graph.engine import create_python_workflow_engine

    engine = create_python_workflow_engine()

    assert engine is not None
    assert type(engine).__name__ == "PythonWorkflowEngine"

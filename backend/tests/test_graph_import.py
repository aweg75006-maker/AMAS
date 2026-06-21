def test_create_graph_compiles_without_eager_external_clients():
    from app.graph.graph import create_graph

    graph = create_graph()

    assert graph is not None
    assert type(graph).__name__ == "CompiledStateGraph"

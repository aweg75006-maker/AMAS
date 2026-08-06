from __future__ import annotations

def create_workflow_engine():
    from app.graph.legacy_langgraph_adapter import create_langgraph_workflow_engine

    return create_langgraph_workflow_engine()

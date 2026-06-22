from __future__ import annotations

from app.core.config import settings
from app.graph.engine import create_python_workflow_engine
from app.graph.legacy_langgraph_adapter import create_langgraph_workflow_engine


def create_workflow_engine():
    if settings.workflow_engine == "langgraph":
        return create_langgraph_workflow_engine()
    return create_python_workflow_engine()

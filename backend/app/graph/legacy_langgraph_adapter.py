from __future__ import annotations

from collections.abc import AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.api.dependencies import CHECKPOINT_DB_PATH
from app.graph.graph import create_graph
from app.graph.state import AgentState


class LangGraphWorkflowEngineAdapter:
    """Legacy LangGraph runner behind the same workflow engine interface."""

    async def astream(
        self,
        initial_state: AgentState,
        config: dict | None = None,
    ) -> AsyncIterator[dict[str, dict]]:
        async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as memory_saver:
            graph = create_graph(memory=memory_saver)
            async for event in graph.astream(initial_state, config=config):
                yield event


def create_langgraph_workflow_engine() -> LangGraphWorkflowEngineAdapter:
    return LangGraphWorkflowEngineAdapter()

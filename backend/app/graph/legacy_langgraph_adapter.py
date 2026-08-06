from __future__ import annotations

from collections.abc import AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.api.dependencies import CHECKPOINT_DB_PATH
from app.graph.graph import create_graph
from app.graph.state import AgentState


class LangGraphWorkflowEngineAdapter:
    """LangGraph runner behind the workflow engine interface."""

    async def astream(
        self,
        initial_state: AgentState | Command,
        config: dict | None = None,
    ) -> AsyncIterator[dict[str, dict]]:
        async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as memory_saver:
            graph = create_graph(memory=memory_saver)
            async for event in graph.astream(initial_state, config=config):
                yield event

    async def get_state(self, config: dict) -> AgentState:
        async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as memory_saver:
            graph = create_graph(memory=memory_saver)
            snapshot = await graph.aget_state(config)
            return dict(snapshot.values)


def create_langgraph_workflow_engine() -> LangGraphWorkflowEngineAdapter:
    return LangGraphWorkflowEngineAdapter()

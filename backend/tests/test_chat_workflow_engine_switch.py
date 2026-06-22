import pytest

from app.api import routes_chat
from app.core.config import settings


class FakePythonEngine:
    async def astream(self, initial_state, config=None):
        yield {"planner": {"plan": ["fake"]}}


@pytest.mark.asyncio
async def test_chat_stream_uses_python_engine_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "workflow_engine", "python")
    monkeypatch.setattr(
        routes_chat,
        "create_python_workflow_engine",
        lambda: FakePythonEngine(),
    )

    events = []
    async for event in routes_chat._stream_workflow_events(
        {"query": "hello"},
        {"configurable": {"thread_id": "t1"}},
    ):
        events.append(event)

    assert events == [{"planner": {"plan": ["fake"]}}]

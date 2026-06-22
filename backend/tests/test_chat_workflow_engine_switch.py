import pytest

from app.api import routes_chat
class FakeWorkflowEngine:
    async def astream(self, initial_state, config=None):
        yield {"planner": {"plan": ["fake"]}}


@pytest.mark.asyncio
async def test_chat_stream_uses_python_engine_when_configured(monkeypatch):
    monkeypatch.setattr(
        routes_chat,
        "create_workflow_engine",
        lambda: FakeWorkflowEngine(),
    )

    events = []
    async for event in routes_chat._stream_workflow_events(
        {"query": "hello"},
        {"configurable": {"thread_id": "t1"}},
    ):
        events.append(event)

    assert events == [{"planner": {"plan": ["fake"]}}]


def test_public_state_update_hides_workflow_event():
    public = routes_chat._public_state_update(
        {
            "plan": ["fake"],
            "_workflow_event": {"engine": "python"},
            "_route_decisions": [{"from_node": "__start__"}],
        }
    )

    assert public == {"plan": ["fake"]}

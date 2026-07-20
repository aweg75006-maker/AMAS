import json

import pytest

from app.graph import engine as engine_module
from app.graph.engine import (
    PythonWorkflowEngine,
    WorkflowPausedError,
)


async def _collect_events(
    engine,
    state,
    *,
    thread_id="t1",
    resume_thread_id=None,
    hitl_pause_before=None,
):
    configurable = {"thread_id": thread_id, "session_id": "s1"}
    if hitl_pause_before:
        configurable["hitl_pause_before"] = hitl_pause_before
    events = []
    async for event in engine.astream(
        state,
        config={"configurable": configurable},
        resume_thread_id=resume_thread_id,
    ):
        events.append(event)
    return events


@pytest.fixture
async def fake_redis(monkeypatch):
    from app.utils.redis_client import RedisClient
    import app.utils.redis_client as redis_module

    client = RedisClient()
    await client.connect()

    async def _fake_get_redis():
        return client

    monkeypatch.setattr(redis_module, "get_redis", _fake_get_redis)
    return client


def _patch_stable_nodes(monkeypatch):
    monkeypatch.setattr(engine_module, "route_query", lambda state: "planner")
    monkeypatch.setattr(engine_module, "plan_node", lambda state: {"plan": ["topic"]})
    monkeypatch.setattr(
        engine_module, "research_node", lambda state: {"search_results": ["evidence"]}
    )
    monkeypatch.setattr(
        engine_module, "write_node", lambda state: {"final_report": "report"}
    )
    monkeypatch.setattr(
        engine_module,
        "review_node",
        lambda state: {
            "review_status": "PASS",
            "review_action": "none",
            "revision_number": state.get("revision_number", 0) + 1,
            "critique": "",
        },
    )


@pytest.mark.asyncio
async def test_hitl_pauses_before_configured_node(monkeypatch, fake_redis):
    _patch_stable_nodes(monkeypatch)
    engine = PythonWorkflowEngine()

    with pytest.raises(WorkflowPausedError) as exc:
        await _collect_events(
            engine,
            {"query": "q", "search_mode": "hybrid", "revision_number": 0},
            thread_id="t-hitl",
            hitl_pause_before="reviewer",
        )

    assert exc.value.details["pause_node"] == "reviewer"
    # 暂停前已落盘 reviewer 断点，可续跑。
    raw = await fake_redis.get_checkpoint("t-hitl", "main")
    assert raw is not None
    assert json.loads(raw)["next_node"] == "reviewer"


@pytest.mark.asyncio
async def test_hitl_resume_injects_human_input(monkeypatch, fake_redis):
    captured = {}

    monkeypatch.setattr(engine_module, "route_query", lambda state: "planner")
    monkeypatch.setattr(engine_module, "plan_node", lambda state: {"plan": ["topic"]})
    monkeypatch.setattr(
        engine_module, "research_node", lambda state: {"search_results": ["evidence"]}
    )
    monkeypatch.setattr(
        engine_module, "write_node", lambda state: {"final_report": "report"}
    )

    def review_node(state):
        # 续跑节点应能消费人工输入。
        captured["human_input"] = state.get("human_input")
        return {
            "review_status": "PASS",
            "review_action": "none",
            "revision_number": state.get("revision_number", 0) + 1,
            "critique": "",
        }

    monkeypatch.setattr(engine_module, "review_node", review_node)
    engine = PythonWorkflowEngine()

    # 在 reviewer 前暂停。
    with pytest.raises(WorkflowPausedError):
        await _collect_events(
            engine,
            {"query": "q", "search_mode": "hybrid", "revision_number": 0},
            thread_id="t-hitl2",
            hitl_pause_before="reviewer",
        )

    # 模拟续跑端点：将人工输入注入断点状态。
    raw = await fake_redis.get_checkpoint("t-hitl2", "main")
    cp = json.loads(raw)
    cp["state"]["human_input"] = "请补充第三节的数据来源"
    await fake_redis.save_checkpoint(
        "t-hitl2", "main", json.dumps(cp, ensure_ascii=False, default=str)
    )

    # 续跑（不再传 hitl_pause_before，避免二次暂停）。
    events = await _collect_events(
        engine, {}, thread_id="t-hitl2", resume_thread_id="t-hitl2"
    )

    assert [list(event)[0] for event in events] == ["reviewer"]
    assert captured["human_input"] == "请补充第三节的数据来源"

import json

import pytest

from app.graph import engine as engine_module
from app.graph.engine import (
    PythonWorkflowEngine,
    WorkflowResumeError,
)
from app.graph.runtime import WorkflowNodeExecutionError


async def _collect_events(engine, state, *, thread_id="t1", resume_thread_id=None):
    events = []
    async for event in engine.astream(
        state,
        config={"configurable": {"thread_id": thread_id, "session_id": "s1"}},
        resume_thread_id=resume_thread_id,
    ):
        events.append(event)
    return events


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


@pytest.fixture
async def fake_redis(monkeypatch):
    """为 checkpoint 提供内存降级 Redis，使引擎不依赖真实 Redis。"""
    from app.utils.redis_client import RedisClient
    import app.utils.redis_client as redis_module

    client = RedisClient()
    await client.connect()

    async def _fake_get_redis():
        return client

    monkeypatch.setattr(redis_module, "get_redis", _fake_get_redis)
    return client


@pytest.mark.asyncio
async def test_checkpoint_saved_on_fresh_run(monkeypatch, fake_redis):
    _patch_stable_nodes(monkeypatch)
    engine = PythonWorkflowEngine()

    await _collect_events(
        engine,
        {"query": "hello", "search_mode": "hybrid", "revision_number": 0},
        thread_id="t-save",
    )

    raw = await fake_redis.get_checkpoint("t-save", "main")
    assert raw is not None
    cp = json.loads(raw)
    assert cp["next_node"] in {"refiner", "reviewer"}
    assert "state" in cp


@pytest.mark.asyncio
async def test_resume_reruns_from_last_checkpoint_after_node_failure(
    monkeypatch, fake_redis
):
    """节点执行中崩溃后，可从断点恢复并接着跑完，不重跑已完成节点。"""
    # 失败开关：首次运行期间 researcher 持续崩溃（无视重试次数），续跑前关闭。
    fail = {"on": True}
    calls = {"researcher": 0}
    monkeypatch.setattr(engine_module, "route_query", lambda state: "planner")
    monkeypatch.setattr(engine_module, "plan_node", lambda state: {"plan": ["topic"]})

    def research_node(state):
        calls["researcher"] += 1
        if fail["on"]:
            raise RuntimeError("simulated crash during research")
        return {"search_results": ["evidence"]}

    monkeypatch.setattr(engine_module, "research_node", research_node)
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

    engine = PythonWorkflowEngine()

    # 第一次执行在 researcher 崩溃，但崩溃前已保存 researcher 断点。
    with pytest.raises(WorkflowNodeExecutionError):
        await _collect_events(
            engine,
            {"query": "hello", "search_mode": "hybrid", "revision_number": 0},
            thread_id="t-resume",
        )

    # 关闭失败开关，从断点恢复：researcher 这次成功，后续节点补齐。
    fail["on"] = False
    events = await _collect_events(engine, {}, resume_thread_id="t-resume")

    assert [list(event)[0] for event in events] == ["researcher", "writer", "reviewer"]
    assert events[-1]["reviewer"]["review_status"] == "PASS"
    # planner 不应被重跑。
    assert "planner" not in [list(event)[0] for event in events]


@pytest.mark.asyncio
async def test_resume_without_checkpoint_raises(monkeypatch, fake_redis):
    _patch_stable_nodes(monkeypatch)
    engine = PythonWorkflowEngine()

    with pytest.raises(WorkflowResumeError) as exc:
        await _collect_events(engine, {}, resume_thread_id="t-never-existed")

    assert exc.value.error_code == "WORKFLOW_RESUME_FAILED"

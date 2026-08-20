import sys

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from langgraph.types import Command

from app.graph.runtime import wrap_node
from app.graph.state import AgentState


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="LangGraph native interrupt requires Python 3.11+ for async graphs",
)
async def test_native_interrupt_resumes_node_with_human_input():
    async def collect_events(graph, workflow_input, config):
        return [event async for event in graph.astream(workflow_input, config=config)]

    def planner(state: AgentState) -> dict:
        return {"plan": [state.get("human_input", "")]}

    workflow = StateGraph(AgentState)
    workflow.add_node("planner", wrap_node("planner", planner))
    workflow.add_edge(START, "planner")
    graph = workflow.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "native-hitl-test"}}

    paused_events = await collect_events(
        graph,
        {"query": "test", "hitl_pause_before": "planner"},
        config,
    )
    interrupt_event = next(
        event["__interrupt__"][0]
        for event in paused_events
        if "__interrupt__" in event
    )
    pause_data = getattr(interrupt_event, "value", interrupt_event)
    assert pause_data["pause_node"] == "planner"
    assert pause_data["thread_id"] == "native-hitl-test"

    resumed_events = await collect_events(
        graph,
        Command(resume={"human_input": "优先使用官方来源"}),
        config,
    )
    planner_update = next(event["planner"] for event in resumed_events if "planner" in event)
    assert planner_update["plan"] == ["优先使用官方来源"]
    assert planner_update["hitl_pause_before"] == ""


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="LangGraph native interrupt requires Python 3.11+ for async graphs",
)
async def test_before_writing_pauses_follow_up_refiner():
    """A follow-up rewrite is still a writing checkpoint from the UI's view."""

    async def collect_events(graph, workflow_input, config):
        return [event async for event in graph.astream(workflow_input, config=config)]

    def refiner(state: AgentState) -> dict:
        return {"final_report": state.get("human_input", "")}

    workflow = StateGraph(AgentState)
    workflow.add_node("refiner", wrap_node("refiner", refiner))
    workflow.add_edge(START, "refiner")
    graph = workflow.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "follow-up-hitl-test"}}

    paused_events = await collect_events(
        graph,
        {"query": "把上一轮答案转换成英文", "hitl_pause_before": "writer"},
        config,
    )
    interrupt_event = next(
        event["__interrupt__"][0]
        for event in paused_events
        if "__interrupt__" in event
    )
    pause_data = getattr(interrupt_event, "value", interrupt_event)
    assert pause_data["pause_node"] == "refiner"
    assert pause_data["thread_id"] == "follow-up-hitl-test"

    resumed_events = await collect_events(
        graph,
        Command(resume={"human_input": "Use concise, natural English."}),
        config,
    )
    refiner_update = next(event["refiner"] for event in resumed_events if "refiner" in event)
    assert refiner_update["final_report"] == "Use concise, natural English."
    assert refiner_update["hitl_pause_before"] == ""

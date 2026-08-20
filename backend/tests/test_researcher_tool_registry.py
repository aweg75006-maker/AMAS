from dataclasses import dataclass

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import START, StateGraph

from app.graph.nodes import researcher
from app.graph.runtime import wrap_node
from app.graph.state import AgentState
from app.tools.registry import ToolRegistry, ToolSpec, reset_tool_registry_for_tests


@dataclass
class FakeDoc:
    page_content: str
    metadata: dict | None = None


class FakeReranker:
    def predict(self, pairs):
        return [0.2 if "本地资料" in text else 0.9 for _query, text in pairs]


def _register_research_tools(registry, calls, *, local_text="本地资料：IRIS 支持工具注册。", grade="YES"):
    registry.register(
        ToolSpec(
            name="rag.retrieve_candidates",
            handler=lambda payload, context: calls.append(("rag.retrieve_candidates", payload))
            or [FakeDoc(local_text, {"source": "manual.pdf"})],
        )
    )
    registry.register(
        ToolSpec(
            name="web.retrieve_candidates",
            handler=lambda payload, context: calls.append(("web.retrieve_candidates", payload))
            or [
                {
                    "text": "网络资料：IRIS 工具注册支持可插拔处理器。",
                    "title": "IRIS 文档",
                    "source_uri": "https://example.com/iris",
                    "source_rank": 1,
                    "query": payload["query"],
                }
            ],
        )
    )
    registry.register(
        ToolSpec(
            name="rag.relevance_grade",
            handler=lambda payload, context: calls.append(("rag.relevance_grade", payload)) or grade,
        )
    )


def test_researcher_fuses_cross_source_candidates_and_reranks(monkeypatch):
    registry = ToolRegistry()
    calls = []
    _register_research_tools(registry, calls)
    monkeypatch.setattr(researcher, "get_reranker", lambda: FakeReranker())

    reset_tool_registry_for_tests(registry)
    try:
        result = researcher.research_node(
            {
                "query": "IRIS 工具注册是什么",
                "plan": [],
                "search_mode": "hybrid",
                "knowledge_base_id": "kb_test",
            }
        )
    finally:
        reset_tool_registry_for_tests(None)

    assert len(result["candidate_pool"]) == 2
    assert result["ranked_evidence"][0]["source_type"] == "web"
    assert result["search_results"][0].startswith("[网络来源: IRIS 文档")
    assert [name for name, _payload in calls] == [
        "rag.retrieve_candidates",
        "web.retrieve_candidates",
        "rag.relevance_grade",
    ]
    assert result["_tool_runs"][0]["tool_name"] == "rag.retrieve_candidates"


def test_researcher_document_mode_stops_without_web_when_docs_irrelevant(monkeypatch):
    registry = ToolRegistry()
    calls = []
    _register_research_tools(registry, calls, local_text="本地资料：完全不相关。", grade="NO")
    monkeypatch.setattr(researcher, "get_reranker", lambda: FakeReranker())

    reset_tool_registry_for_tests(registry)
    try:
        result = researcher.research_node(
            {
                "query": "IRIS 工具注册是什么",
                "plan": [],
                "search_mode": "document",
                "knowledge_base_id": "kb_test",
            }
        )
    finally:
        reset_tool_registry_for_tests(None)

    assert result["should_stop"] is True
    assert all(name != "web.retrieve_candidates" for name, _payload in calls)
    assert any("Document Only 模式" in item for item in result["search_results"])


def test_researcher_refines_the_query_until_the_retrieval_budget_is_used(monkeypatch):
    registry = ToolRegistry()
    calls = []
    _register_research_tools(registry, calls, grade="NO")
    monkeypatch.setattr(researcher, "get_reranker", lambda: FakeReranker())
    monkeypatch.setattr(researcher.settings, "rag_max_retrieval_iterations", 1)

    reset_tool_registry_for_tests(registry)
    try:
        result = researcher.research_node(
            {
                "query": "IRIS 工具注册是什么",
                "plan": [],
                "search_mode": "hybrid",
                "knowledge_base_id": "kb_test",
            }
        )
    finally:
        reset_tool_registry_for_tests(None)

    local_queries = [payload["query"] for name, payload in calls if name == "rag.retrieve_candidates"]
    assert result["should_stop"] is False
    assert result["retrieval_iteration"] == 1
    assert len(local_queries) == 2
    assert "权威来源" in local_queries[-1]


def test_researcher_uses_structured_follow_up_queries_from_evidence_grade(monkeypatch):
    registry = ToolRegistry()
    calls = []
    _register_research_tools(
        registry,
        calls,
        grade={
            "sufficient": False,
            "coverage_gap": "缺少官方统计数据",
            "follow_up_queries": ["IRIS 官方统计数据", "IRIS release metrics"],
        },
    )
    monkeypatch.setattr(researcher, "get_reranker", lambda: FakeReranker())
    monkeypatch.setattr(researcher.settings, "rag_max_retrieval_iterations", 1)

    reset_tool_registry_for_tests(registry)
    try:
        result = researcher.research_node(
            {
                "query": "IRIS 工具注册是什么",
                "plan": [],
                "search_mode": "hybrid",
                "knowledge_base_id": "kb_test",
            }
        )
    finally:
        reset_tool_registry_for_tests(None)

    local_queries = [payload["query"] for name, payload in calls if name == "rag.retrieve_candidates"]
    assert result["coverage_gap"] == "缺少官方统计数据"
    assert "IRIS 官方统计数据" in local_queries
    assert "IRIS release metrics" in local_queries


def test_research_subgraph_exposes_the_retrieval_loop():
    mermaid = researcher.create_research_graph().get_graph().draw_mermaid()

    for node_name in (
        "initialize",
        "retrieve_local",
        "retrieve_web",
        "fuse_candidates",
        "rerank_candidates",
        "evaluate_evidence",
        "refine_query",
        "finalize",
    ):
        assert node_name in mermaid


@pytest.mark.asyncio
async def test_researcher_streams_structured_subgraph_progress(monkeypatch):
    registry = ToolRegistry()
    calls = []
    _register_research_tools(registry, calls)
    monkeypatch.setattr(researcher, "get_reranker", lambda: FakeReranker())
    monkeypatch.setattr(researcher.settings, "rag_max_retrieval_iterations", 0)

    workflow = StateGraph(AgentState)
    workflow.add_node("researcher", wrap_node("researcher", researcher.research_node))
    workflow.add_edge(START, "researcher")
    reset_tool_registry_for_tests(registry)
    try:
        async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
            graph = workflow.compile(checkpointer=checkpointer)
            stream_events = [
                event
                async for event in graph.astream(
                    {
                        "query": "IRIS 工具注册是什么",
                        "plan": [],
                        "search_mode": "hybrid",
                        "knowledge_base_id": "kb_test",
                    },
                    config={"configurable": {"thread_id": "research-progress-sqlite"}},
                    stream_mode=["updates", "custom"],
                )
            ]
    finally:
        reset_tool_registry_for_tests(None)

    progress = [payload for mode, payload in stream_events if mode == "custom"]
    assert progress[0]["stage"] == "initialize"
    assert progress[0]["status"] == "running"
    assert progress[-1]["stage"] == "finalize"
    assert progress[-1]["status"] == "completed"
    assert progress[-1]["details"]["evidence_count"] == 2

    completed_stages = {
        event["stage"] for event in progress if event["status"] == "completed"
    }
    assert completed_stages == {
        "initialize",
        "retrieve_local",
        "retrieve_web",
        "fuse_candidates",
        "rerank_candidates",
        "evaluate_evidence",
        "finalize",
    }

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.core.logging import get_logger
from app.graph.policies.researcher_policy import (
    DOCUMENT_IRRELEVANT_MESSAGE,
    DOCUMENT_ONLY_STOP_MESSAGE,
)
from app.graph.state import AgentState
from app.rag.engine import get_reranker
from app.tools.runtime import ToolRuntime

logger = get_logger("iris.graph.researcher")


class ResearchState(TypedDict, total=False):
    workflow_state: dict[str, Any]
    query: str
    plan: list[str]
    search_mode: str
    knowledge_base_id: str
    active_queries: list[str]
    local_candidates: list[dict[str, Any]]
    web_candidates: list[dict[str, Any]]
    candidate_pool: list[dict[str, Any]]
    ranked_evidence: list[dict[str, Any]]
    context_sufficient: bool
    retrieval_iteration: int
    max_retrieval_iterations: int
    coverage_gap: str
    search_results: list[str]
    should_stop: bool
    tool_runs: list[dict[str, Any]]


def _append_tool_run(tool_runs: list[dict[str, Any]], result: Any) -> None:
    if result.run is not None:
        tool_runs.append(result.run.to_dict())


def _unique_queries(values: list[str], *, limit: int = 4) -> list[str]:
    queries = []
    seen = set()
    for value in values:
        normalized = " ".join((value or "").split())
        if normalized and normalized not in seen:
            queries.append(normalized)
            seen.add(normalized)
        if len(queries) >= limit:
            break
    return queries


def _candidate_id(source_type: str, source_uri: str, text: str) -> str:
    raw = f"{source_type}\n{source_uri}\n{' '.join(text.split()).lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _local_candidate(document: Any, query: str, source_rank: int) -> dict[str, Any] | None:
    text = str(getattr(document, "page_content", "")).strip()
    if not text:
        return None
    metadata = dict(getattr(document, "metadata", {}) or {})
    source_uri = str(metadata.get("source", ""))
    title = str(metadata.get("title") or metadata.get("filename") or source_uri or "本地知识库文档")
    return {
        "id": _candidate_id("local", source_uri, text),
        "text": text,
        "title": title,
        "source_type": "local",
        "source_uri": source_uri,
        "retrieval_score": 0.0,
        "source_rank": source_rank,
        "query": query,
        "metadata": metadata,
    }


def _web_candidate(raw: dict[str, Any]) -> dict[str, Any] | None:
    text = str(raw.get("text", "")).strip()
    if not text:
        return None
    source_uri = str(raw.get("source_uri", ""))
    return {
        "id": _candidate_id("web", source_uri, text),
        "text": text,
        "title": str(raw.get("title", "") or source_uri or "网络来源"),
        "source_type": "web",
        "source_uri": source_uri,
        "retrieval_score": float(raw.get("retrieval_score", 0.0) or 0.0),
        "source_rank": int(raw.get("source_rank", 0) or 0),
        "query": str(raw.get("query", "")),
        "metadata": {},
    }


def initialize_research(state: ResearchState) -> dict[str, Any]:
    queries = _unique_queries([state["query"], *state.get("plan", [])])
    return {
        "active_queries": queries or [state["query"]],
        "local_candidates": [],
        "web_candidates": [],
        "candidate_pool": state.get("candidate_pool", []),
        "ranked_evidence": [],
        "context_sufficient": False,
        "retrieval_iteration": state.get("retrieval_iteration", 0),
        "max_retrieval_iterations": state.get(
            "max_retrieval_iterations", settings.rag_max_retrieval_iterations
        ),
        "tool_runs": state.get("tool_runs", []),
    }


def retrieve_local(state: ResearchState) -> dict[str, Any]:
    runtime = ToolRuntime(node_name="researcher")
    tool_runs = list(state.get("tool_runs", []))
    candidates = []
    for query in state.get("active_queries", [state["query"]]):
        result = runtime.run_registered(
            "rag.retrieve_candidates",
            {"query": query, "knowledge_base_id": state.get("knowledge_base_id", "kb_default")},
            state=state["workflow_state"],
            input_summary=query,
            metadata={"knowledge_base_id": state.get("knowledge_base_id", "kb_default")},
        )
        _append_tool_run(tool_runs, result)
        if not result.ok:
            logger.warning("rag_candidate_retrieval_failed")
            continue
        for rank, document in enumerate(result.value or [], start=1):
            candidate = _local_candidate(document, query, rank)
            if candidate:
                candidates.append(candidate)
    return {"local_candidates": candidates, "tool_runs": tool_runs}


def route_after_local(state: ResearchState) -> Literal["retrieve_web", "fuse_candidates"]:
    return "fuse_candidates" if state.get("search_mode") == "document" else "retrieve_web"


def retrieve_web(state: ResearchState) -> dict[str, Any]:
    runtime = ToolRuntime(node_name="researcher")
    tool_runs = list(state.get("tool_runs", []))
    candidates = []
    for query in state.get("active_queries", [state["query"]]):
        result = runtime.run_registered(
            "web.retrieve_candidates",
            {"query": query},
            state=state["workflow_state"],
            input_summary=query,
            metadata={"retrieval_iteration": state.get("retrieval_iteration", 0)},
        )
        _append_tool_run(tool_runs, result)
        if not result.ok:
            logger.warning("web_candidate_retrieval_failed")
            continue
        for raw in result.value or []:
            candidate = _web_candidate(raw)
            if candidate:
                candidates.append(candidate)
    return {"web_candidates": candidates, "tool_runs": tool_runs}


def fuse_candidates(state: ResearchState) -> dict[str, Any]:
    fused = []
    seen = set()
    for candidate in [
        *state.get("candidate_pool", []),
        *state.get("local_candidates", []),
        *state.get("web_candidates", []),
    ]:
        candidate_id = candidate["id"]
        if candidate_id not in seen:
            fused.append(candidate)
            seen.add(candidate_id)
    logger.info(
        "research_candidates_fused",
        extra={"candidate_count": len(fused), "iteration": state.get("retrieval_iteration", 0)},
    )
    return {"candidate_pool": fused}


def rerank_candidates(state: ResearchState) -> dict[str, Any]:
    candidates = list(state.get("candidate_pool", []))
    if not candidates:
        return {"ranked_evidence": []}
    try:
        reranker = get_reranker()
        scores = reranker.predict([(state["query"], candidate["text"]) for candidate in candidates])
        ranked = [
            {**candidate, "rerank_score": float(score)}
            for candidate, score in sorted(
                zip(candidates, scores), key=lambda item: float(item[1]), reverse=True
            )
        ]
    except Exception as exc:
        logger.warning("unified_rerank_unavailable", extra={"error": str(exc)[:300]})
        ranked = sorted(
            candidates,
            key=lambda candidate: (candidate.get("retrieval_score", 0.0), -candidate.get("source_rank", 0)),
            reverse=True,
        )
    return {"ranked_evidence": ranked[: settings.rag_top_k]}


def evaluate_evidence(state: ResearchState) -> dict[str, Any]:
    ranked = state.get("ranked_evidence", [])
    if not ranked:
        return {"context_sufficient": False, "coverage_gap": "没有检索到可用证据"}
    context = "\n\n".join(
        f"[{candidate['source_type']} | {candidate['title']}] {candidate['text']}"
        for candidate in ranked
    )
    runtime = ToolRuntime(node_name="researcher")
    tool_runs = list(state.get("tool_runs", []))
    result = runtime.run_registered(
        "rag.relevance_grade",
        {"query": state["query"], "document_context": context},
        state=state["workflow_state"],
        input_summary=f"{state['query']}\n{context[:500]}",
        metadata={"candidate_count": len(ranked)},
    )
    _append_tool_run(tool_runs, result)
    sufficient = bool(result.ok and "YES" in str(result.value).upper())
    return {
        "context_sufficient": sufficient,
        "coverage_gap": "" if sufficient else "现有候选无法充分回答问题",
        "tool_runs": tool_runs,
    }


def route_after_evaluation(state: ResearchState) -> Literal["finalize", "refine_query"]:
    if state.get("context_sufficient") or state.get("search_mode") == "document":
        return "finalize"
    if state.get("retrieval_iteration", 0) >= state.get("max_retrieval_iterations", 0):
        return "finalize"
    return "refine_query"


def refine_query(state: ResearchState) -> dict[str, Any]:
    iteration = state.get("retrieval_iteration", 0) + 1
    refined = f"{state['query']} 权威来源 关键事实 数据"
    logger.info("research_query_refined", extra={"iteration": iteration})
    return {
        "active_queries": [refined],
        "local_candidates": [],
        "web_candidates": [],
        "retrieval_iteration": iteration,
    }


def _format_evidence(candidate: dict[str, Any]) -> str:
    source = "本地文档" if candidate["source_type"] == "local" else "网络来源"
    citation = candidate["title"]
    if candidate.get("source_uri"):
        citation = f"{citation} | {candidate['source_uri']}"
    return f"[{source}: {citation}]\n{candidate['text']}"


def finalize_research(state: ResearchState) -> dict[str, Any]:
    ranked = state.get("ranked_evidence", [])
    results = [_format_evidence(candidate) for candidate in ranked]
    sufficient = state.get("context_sufficient", False)
    document_mode = state.get("search_mode") == "document"
    if not sufficient and document_mode:
        results.insert(0, DOCUMENT_IRRELEVANT_MESSAGE)
        results.append(DOCUMENT_ONLY_STOP_MESSAGE)
    return {
        "search_results": results,
        "should_stop": bool(document_mode and not sufficient),
    }


@lru_cache
def create_research_graph():
    workflow = StateGraph(ResearchState)
    workflow.add_node("initialize", initialize_research)
    workflow.add_node("retrieve_local", retrieve_local)
    workflow.add_node("retrieve_web", retrieve_web)
    workflow.add_node("fuse_candidates", fuse_candidates)
    workflow.add_node("rerank_candidates", rerank_candidates)
    workflow.add_node("evaluate_evidence", evaluate_evidence)
    workflow.add_node("refine_query", refine_query)
    workflow.add_node("finalize", finalize_research)
    workflow.add_edge(START, "initialize")
    workflow.add_edge("initialize", "retrieve_local")
    workflow.add_conditional_edges("retrieve_local", route_after_local)
    workflow.add_edge("retrieve_web", "fuse_candidates")
    workflow.add_edge("fuse_candidates", "rerank_candidates")
    workflow.add_edge("rerank_candidates", "evaluate_evidence")
    workflow.add_conditional_edges("evaluate_evidence", route_after_evaluation)
    workflow.add_edge("refine_query", "retrieve_local")
    workflow.add_edge("finalize", END)
    return workflow.compile()


def research_node(state: AgentState) -> dict[str, Any]:
    """Run the retrieval orchestration as a dedicated LangGraph subgraph."""
    logger.info(
        "researcher_started",
        extra={
            "search_mode": state.get("search_mode", "hybrid"),
            "knowledge_base_id": state.get("knowledge_base_id", "kb_default"),
            "query_length": len(state["query"]),
            "plan_count": len(state.get("plan", [])),
        },
    )
    result = create_research_graph().invoke(
        {
            "workflow_state": dict(state),
            "query": state["query"],
            "plan": state.get("plan", []),
            "search_mode": state.get("search_mode", "hybrid"),
            "knowledge_base_id": state.get("knowledge_base_id", "kb_default"),
            "max_retrieval_iterations": settings.rag_max_retrieval_iterations,
        }
    )
    logger.info(
        "researcher_completed",
        extra={
            "result_count": len(result.get("search_results", [])),
            "candidate_count": len(result.get("candidate_pool", [])),
            "iteration": result.get("retrieval_iteration", 0),
        },
    )
    return {
        "search_results": result.get("search_results", []),
        "should_stop": result.get("should_stop", False),
        "candidate_pool": result.get("candidate_pool", []),
        "ranked_evidence": result.get("ranked_evidence", []),
        "retrieval_iteration": result.get("retrieval_iteration", 0),
        "_tool_runs": result.get("tool_runs", []),
    }

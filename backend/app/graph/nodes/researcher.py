from __future__ import annotations

# 路径引导：确保本文件无论用 `python -m app.graph.nodes.researcher` 还是
# 直接 `python <path>/nodes/researcher.py` 运行，顶层的 `from app...` 导入都能解析。
import sys
from pathlib import Path

_backend_root = Path(__file__).resolve().parents[3]
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

import hashlib
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Literal, TypedDict

from langgraph.config import get_stream_writer
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
    """Researcher 子图的内部状态，独立于主图的 AgentState。"""
    workflow_state: dict[str, Any]     # 主图 AgentState 的快照，供工具调用时读取
    query: str                         # 用户原始问题
    plan: list[str]                    # Planner 拆解的搜索子关键词
    retrieval_hints: list[str]         # 额外的检索提示（含人工补充）
    search_mode: str                   # "document"（仅本地文档）或 "hybrid"（本地+网络）
    knowledge_base_id: str             # 知识库 ID，用于隔离不同用户的向量空间
    active_queries: list[str]          # 当前轮实际使用的搜索关键词（去重后）
    local_candidates: list[dict[str, Any]]   # 本地 ChromaDB 召回的候选文档
    web_candidates: list[dict[str, Any]]     # Tavily 网络搜索召回的候选
    candidate_pool: list[dict[str, Any]]     # 融合去重后的候选池
    ranked_evidence: list[dict[str, Any]]    # Cross-Encoder 重排序后的 top-k 证据
    context_sufficient: bool           # LLM 判断证据是否充分
    retrieval_iteration: int           # 当前是第几轮迭代检索（从 0 开始）
    max_retrieval_iterations: int      # 最大迭代次数（默认 2）
    coverage_gap: str                  # 证据不足时，LLM 指出的具体缺口
    follow_up_queries: list[str]       # 证据不足时，LLM 建议的补充搜索关键词
    search_results: list[str]          # 最终输出：格式化的证据列表
    should_stop: bool                  # Document Only 模式下文档不相关时置 True
    tool_runs: list[dict[str, Any]]    # 工具调用追踪记录


_RESEARCH_STAGE_META = {
    "initialize": ("Query planning", "生成并去重检索关键词"),
    "retrieve_local": ("Local retrieval", "从本地知识库召回候选证据"),
    "retrieve_web": ("Web retrieval", "从网络搜索召回候选来源"),
    "fuse_candidates": ("Candidate fusion", "合并并去重多来源候选"),
    "rerank_candidates": ("Semantic rerank", "按问题相关性精排候选证据"),
    "evaluate_evidence": ("Evidence check", "判断当前证据是否足够回答问题"),
    "refine_query": ("Query refinement", "根据证据缺口生成补充检索词"),
    "finalize": ("Evidence package", "整理可供写作节点使用的最终证据"),
}


def _progress_details(stage: str, state: ResearchState) -> dict[str, Any]:
    """只暴露适合前端展示的计数和短摘要，避免推送大段候选正文。"""
    if stage == "initialize":
        return {
            "query_count": len(state.get("active_queries", [])),
            "queries": state.get("active_queries", [])[:4],
        }
    if stage == "retrieve_local":
        return {
            "candidate_count": len(state.get("local_candidates", [])),
            "query_count": len(state.get("active_queries", [])),
        }
    if stage == "retrieve_web":
        return {
            "candidate_count": len(state.get("web_candidates", [])),
            "query_count": len(state.get("active_queries", [])),
        }
    if stage == "fuse_candidates":
        return {"candidate_count": len(state.get("candidate_pool", []))}
    if stage == "rerank_candidates":
        ranked = state.get("ranked_evidence", [])
        return {
            "evidence_count": len(ranked),
            "top_score": round(float(ranked[0].get("rerank_score", 0.0)), 3) if ranked else None,
        }
    if stage == "evaluate_evidence":
        return {
            "sufficient": bool(state.get("context_sufficient")),
            "coverage_gap": state.get("coverage_gap", "")[:180],
            "follow_up_queries": state.get("follow_up_queries", [])[:3],
        }
    if stage == "refine_query":
        return {
            "query_count": len(state.get("active_queries", [])),
            "queries": state.get("active_queries", [])[:3],
        }
    if stage == "finalize":
        return {
            "evidence_count": len(state.get("search_results", [])),
            "should_stop": bool(state.get("should_stop")),
        }
    return {}


def _emit_research_progress(
    state: ResearchState,
    stage: str,
    status: str,
    *,
    progress_writer: Callable[[dict[str, Any]], None] | None = None,
    duration_ms: int | None = None,
    error: str = "",
) -> None:
    if not callable(progress_writer):
        return
    label, message = _RESEARCH_STAGE_META[stage]
    payload = {
        "kind": "research_progress",
        "agent": "researcher",
        "stage": stage,
        "status": status,
        "label": label,
        "message": message,
        "iteration": int(state.get("retrieval_iteration", 0)) + 1,
        "details": _progress_details(stage, state),
    }
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if error:
        payload["error"] = error[:300]
    progress_writer(payload)


def _tracked_stage(
    stage: str,
    fn: Callable[[ResearchState], dict[str, Any]],
    progress_writer: Callable[[dict[str, Any]], None] | None = None,
) -> Callable[[ResearchState], dict[str, Any]]:
    """为 Researcher 子图节点增加开始/完成/失败的实时观测事件。"""
    def tracked(state: ResearchState) -> dict[str, Any]:
        _emit_research_progress(
            state,
            stage,
            "running",
            progress_writer=progress_writer,
        )
        started_at = time.perf_counter()
        try:
            update = fn(state)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            _emit_research_progress(
                state,
                stage,
                "failed",
                progress_writer=progress_writer,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _emit_research_progress(
            {**state, **update},
            stage,
            "completed",
            progress_writer=progress_writer,
            duration_ms=duration_ms,
        )
        return update

    return tracked


def _append_tool_run(tool_runs: list[dict[str, Any]], result: Any) -> None:
    """把一次工具调用的执行快照追加到追踪列表中。"""
    if result.run is not None:
        tool_runs.append(result.run.to_dict())


def _unique_queries(values: list[str], *, limit: int = 4) -> list[str]:
    """对搜索关键词去重并截断，避免重复搜索浪费资源。"""
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
    """用 SHA256 为每个候选文档生成唯一 ID，用于去重。"""
    raw = f"{source_type}\n{source_uri}\n{' '.join(text.split()).lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _local_candidate(document: Any, query: str, source_rank: int) -> dict[str, Any] | None:
    """把 ChromaDB 返回的 LangChain Document 对象转成统一的候选格式。"""
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
    """把 Tavily 返回的原始 dict 转成统一的候选格式。"""
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
    """子图入口：从 query、plan、hints 中提取去重的搜索关键词，初始化状态。"""
    queries = _unique_queries(
        [state["query"], *state.get("plan", []), *state.get("retrieval_hints", [])]
    )
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
        "coverage_gap": "",
        "follow_up_queries": [],
    }


def retrieve_local(state: ResearchState) -> dict[str, Any]:
    """对每个搜索关键词从 ChromaDB 本地知识库召回候选文档（fetch_k=20）。"""
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
    """本地检索后的路由：document 模式跳过网络搜索，hybrid 模式继续。"""
    return "fuse_candidates" if state.get("search_mode") == "document" else "retrieve_web"


def retrieve_web(state: ResearchState) -> dict[str, Any]:
    """对每个搜索关键词从 Tavily API 召回网络候选结果。"""
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


def _dedup_key(candidate: dict[str, Any]) -> tuple:
    """去重主键。

    - 网络候选：以 (source_type, source_uri) 为主键。Tavily 对同一网页在不同调用里
      返回的文本常有细微差异，若只按全文 SHA256 去重会漏掉，导致同一来源反复进入
      top-k。改为按 URL 去重，并保留文本更长（信息更全）的一条。
    - 本地候选：保留原有基于全文 SHA256 的去重，避免把同一文档的不同切片误合并。
    """
    if candidate.get("source_type") == "web" and candidate.get("source_uri"):
        return ("web", candidate["source_uri"])
    return ("id", candidate["id"])


def fuse_candidates(state: ResearchState) -> dict[str, Any]:
    """把本地、网络、历史候选按去重键合并到 candidate_pool（同 URL 网络页只留最长文本）。"""
    best: dict[tuple, dict[str, Any]] = {}
    order: list[tuple] = []
    for candidate in [
        *state.get("candidate_pool", []),
        *state.get("local_candidates", []),
        *state.get("web_candidates", []),
    ]:
        key = _dedup_key(candidate)
        if key not in best:
            best[key] = candidate
            order.append(key)
        elif len(candidate.get("text", "")) > len(best[key].get("text", "")):
            # 同一键保留文本更长者，信息更全
            best[key] = candidate
    fused = [best[key] for key in order]
    logger.info(
        "research_candidates_fused",
        extra={"candidate_count": len(fused), "iteration": state.get("retrieval_iteration", 0)},
    )
    return {"candidate_pool": fused}


def rerank_candidates(state: ResearchState) -> dict[str, Any]:
    """用 Cross-Encoder 对所有候选做语义精排，取 top_k 作为最终证据。"""
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
    """调用 LLM 判断证据是否充分回答问题，不充分时返回缺口和补充搜索建议。"""
    ranked = state.get("ranked_evidence", [])
    if not ranked:
        return {
            "context_sufficient": False,
            "coverage_gap": "没有检索到可用证据",
            "follow_up_queries": [],
        }
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
    if result.ok and isinstance(result.value, dict):
        assessment = result.value
    else:
        assessment = {
            "sufficient": bool(result.ok and "YES" in str(result.value).upper()),
            "coverage_gap": "",
            "follow_up_queries": [],
        }
    sufficient = assessment.get("sufficient") is True or (
        str(assessment.get("sufficient", "")).strip().lower() == "true"
    )
    coverage_gap = str(assessment.get("coverage_gap", "")).strip()
    raw_follow_up_queries = assessment.get("follow_up_queries", [])
    if not isinstance(raw_follow_up_queries, list):
        raw_follow_up_queries = []
    follow_up_queries = _unique_queries(raw_follow_up_queries, limit=3)
    return {
        "context_sufficient": sufficient,
        "coverage_gap": "" if sufficient else coverage_gap or "现有候选无法充分回答问题",
        "follow_up_queries": [] if sufficient else follow_up_queries,
        "tool_runs": tool_runs,
    }


def route_after_evaluation(state: ResearchState) -> Literal["finalize", "refine_query"]:
    """证据评估后的路由：充分或达到最大迭代次数就结束，否则用新关键词重试。"""
    if state.get("context_sufficient") or state.get("search_mode") == "document":
        return "finalize"
    if state.get("retrieval_iteration", 0) >= state.get("max_retrieval_iterations", 0):
        return "finalize"
    return "refine_query"


def refine_query(state: ResearchState) -> dict[str, Any]:
    """证据不足时，用 LLM 建议的 follow_up_queries 生成新的搜索关键词，进入下一轮检索。"""
    iteration = state.get("retrieval_iteration", 0) + 1
    suggested = _unique_queries(state.get("follow_up_queries", []), limit=3)
    refined = suggested or [f"{state['query']} 权威来源 关键事实 数据"]
    logger.info(
        "research_query_refined",
        extra={"iteration": iteration, "query_count": len(refined)},
    )
    return {
        "active_queries": refined,
        "local_candidates": [],
        "web_candidates": [],
        "retrieval_iteration": iteration,
    }


def _format_evidence(candidate: dict[str, Any]) -> str:
    """把单个候选格式化为带来源标注的证据文本。"""
    source = "本地文档" if candidate["source_type"] == "local" else "网络来源"
    citation = candidate["title"]
    if candidate.get("source_uri"):
        citation = f"{citation} | {candidate['source_uri']}"
    return f"[{source}: {citation}]\n{candidate['text']}"


def finalize_research(state: ResearchState) -> dict[str, Any]:
    """子图出口：把排序后的证据格式化为 search_results，Document Only 模式下不相关则熔断。"""
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


def _build_research_graph(
    progress_writer: Callable[[dict[str, Any]], None] | None = None,
):
    """构建 Researcher 子图：initialize → retrieve_local → [retrieve_web] → fuse → rerank → evaluate → [refine] → finalize。"""
    workflow = StateGraph(ResearchState)
    workflow.add_node("initialize", _tracked_stage("initialize", initialize_research, progress_writer))
    workflow.add_node("retrieve_local", _tracked_stage("retrieve_local", retrieve_local, progress_writer))
    workflow.add_node("retrieve_web", _tracked_stage("retrieve_web", retrieve_web, progress_writer))
    workflow.add_node("fuse_candidates", _tracked_stage("fuse_candidates", fuse_candidates, progress_writer))
    workflow.add_node("rerank_candidates", _tracked_stage("rerank_candidates", rerank_candidates, progress_writer))
    workflow.add_node("evaluate_evidence", _tracked_stage("evaluate_evidence", evaluate_evidence, progress_writer))
    workflow.add_node("refine_query", _tracked_stage("refine_query", refine_query, progress_writer))
    workflow.add_node("finalize", _tracked_stage("finalize", finalize_research, progress_writer))
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


@lru_cache
def create_research_graph():
    """返回不带实时 writer 的可复用子图，供测试和命令行直接调用。"""
    return _build_research_graph()


def research_node(state: AgentState) -> dict[str, Any]:
    """主图调用入口：构造 ResearchState，运行子图，把结果映射回 AgentState。"""
    logger.info(
        "researcher_started",
        extra={
            "search_mode": state.get("search_mode", "hybrid"),
            "knowledge_base_id": state.get("knowledge_base_id", "kb_default"),
            "query_length": len(state["query"]),
            "plan_count": len(state.get("plan", [])),
        },
    )
    try:
        progress_writer = get_stream_writer()
    except RuntimeError:
        # research_node 也支持在单元测试/命令行中脱离 LangGraph 直接运行。
        progress_writer = None

    # writer 只捕获在本次子图的节点闭包里，绝不能进入可持久化状态；
    # AsyncSqliteSaver 使用 msgpack，函数对象无法被序列化。
    result = _build_research_graph(progress_writer).invoke(
        {
            "workflow_state": dict(state),
            "query": state["query"],
            "plan": state.get("plan", []),
            "retrieval_hints": [
                *state.get("retrieval_hints", []),
                *([state["human_input"]] if state.get("human_input") else []),
            ],
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
        "coverage_gap": result.get("coverage_gap", ""),
        "follow_up_queries": result.get("follow_up_queries", []),
        "_tool_runs": result.get("tool_runs", []),
    }


if __name__ == "__main__":
    # 路径引导已由模块顶部完成（sys.path 已包含 backend 根目录），
    # 因此顶层的 `from app...` 导入和这里的运行都能直接解析。
    import argparse
    import textwrap
    import traceback

    from app.core.config import settings

    _DEFAULT_QUERY = "请检索并说明 2024 年中国新能源汽车出口的主要市场与增长数据。"

    parser = argparse.ArgumentParser(
        description="Researcher 子图独立测试：验证 搜索 / RAG(重排序) / Agentic(迭代评估) 效果。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            示例：
              python -m app.graph.nodes.researcher -q "什么是 RAG 的 rerank？"
              python -m app.graph.nodes.researcher -q "..." -m document --kb kb_default
              python -m app.graph.nodes.researcher -q "..." --plan "子问题1" "子问题2" --max-iter 3
            """
        ),
    )
    parser.add_argument("-q", "--query", default=_DEFAULT_QUERY, help="要测试的用户问题")
    parser.add_argument(
        "-m", "--mode", choices=["hybrid", "document"], default="hybrid",
        help="hybrid=本地知识库+网络搜索；document=仅本地知识库",
    )
    parser.add_argument("--kb", default="kb_default", help="知识库 ID（用于隔离不同用户的向量空间）")
    parser.add_argument("--plan", nargs="*", default=[], help="Planner 拆解的子搜索关键词")
    parser.add_argument("--hints", nargs="*", default=[], help="额外检索提示（含人工补充）")
    parser.add_argument(
        "--max-iter", type=int, default=settings.rag_max_retrieval_iterations,
        help="最大迭代检索轮数（默认取 settings.rag_max_retrieval_iterations）",
    )
    args = parser.parse_args()

    # 构造子图初始状态（对应 research_node 透传给子图的字段）。
    # workflow_state 是主图状态的快照，供工具调用时读取；独立测试时给空字典即可。
    initial_state: dict = {
        "workflow_state": {},
        "query": args.query,
        "plan": list(args.plan),
        "retrieval_hints": list(args.hints),
        "search_mode": args.mode,
        "knowledge_base_id": args.kb,
        "max_retrieval_iterations": args.max_iter,
        "retrieval_iteration": 0,
        "candidate_pool": [],
        "tool_runs": [],
    }

    print("=" * 72)
    print("Researcher 子图 · 独立效果测试")
    print("=" * 72)
    print(f"query           : {args.query}")
    print(f"search_mode     : {args.mode}")
    print(f"knowledge_base  : {args.kb}")
    print(f"plan            : {args.plan or '(无)'}")
    print(f"retrieval_hints : {args.hints or '(无)'}")
    print(f"max_iterations  : {args.max_iter}")
    print("-" * 72)
    print("[运行] 调用子图（stream_mode=updates，逐节点追踪）...\n")

    graph = create_research_graph()
    state: dict = dict(initial_state)
    try:
        for chunk in graph.stream(initial_state, stream_mode="updates"):
            for node, update in chunk.items():
                if not isinstance(update, dict):
                    continue
                state.update(update)

                # ── 搜索（检索）维度 ──
                if node == "initialize":
                    print(f"[init] 去重后的搜索关键词: {state.get('active_queries')}")
                elif node == "retrieve_local":
                    print(f"[retrieve_local] 本地召回候选数: {len(state.get('local_candidates', []))}")
                elif node == "retrieve_web":
                    print(f"[retrieve_web]    网络召回候选数: {len(state.get('web_candidates', []))}")
                elif node == "fuse_candidates":
                    print(f"[fuse]          去重后候选池大小: {len(state.get('candidate_pool', []))}")

                # ── RAG（重排序）维度 ──
                elif node == "rerank_candidates":
                    ranked = state.get("ranked_evidence", [])
                    print(f"[rerank]         Cross-Encoder 精排后 top-k 证据数: {len(ranked)}")
                    for idx, cand in enumerate(ranked, start=1):
                        src = "本地" if cand.get("source_type") == "local" else "网络"
                        score = cand.get("rerank_score", cand.get("retrieval_score", 0.0))
                        snippet = " ".join(str(cand.get("text", "")).split())[:120]
                        print(f"        {idx}. [{src}] {cand.get('title', '')}  (score={score:.4f})")
                        print(f"            {snippet}")

                # ── Agentic（证据评估与迭代）维度 ──
                elif node == "evaluate_evidence":
                    sufficient = state.get("context_sufficient")
                    print(f"[evaluate]       证据是否充分: {sufficient}")
                    if not sufficient:
                        print(f"[evaluate]       证据缺口: {state.get('coverage_gap', '')}")
                        print(f"[evaluate]       建议补充检索: {state.get('follow_up_queries', [])}")
                elif node == "refine_query":
                    print(
                        f"[refine]         进入第 {state.get('retrieval_iteration')} 轮检索 -> "
                        f"新搜索关键词: {state.get('active_queries')}"
                    )
                elif node == "finalize":
                    print(
                        f"[finalize]       输出证据条数: {len(state.get('search_results', []))}  "
                        f"should_stop={state.get('should_stop')}"
                    )

        print("\n" + "-" * 72)
        print("【最终结论】")
        print(f"  实际检索轮数   : {state.get('retrieval_iteration', 0)}")
        print(f"  候选池总大小   : {len(state.get('candidate_pool', []))}")
        print(f"  证据是否充分   : {state.get('context_sufficient')}")
        print(f"  证据缺口       : {state.get('coverage_gap', '') or '(无)'}")
        print(f"  补充检索建议   : {state.get('follow_up_queries', []) or '(无)'}")

        print("\n【最终证据 (search_results)】")
        for idx, item in enumerate(state.get("search_results", []), start=1):
            print(f"\n--- 证据 {idx} ---")
            print(item)

        print("\n【工具调用追踪】")
        for run in state.get("tool_runs", []):
            status = run.get("status")
            name = run.get("tool_name")
            dur = run.get("duration_ms")
            err = run.get("error_message", "")
            marker = "OK  " if status == "succeeded" else "FAIL"
            line = f"  [{marker}] {name}  status={status}  {dur}ms"
            if err:
                line += f"  err={err[:200]}"
            print(line)

        print("\n" + "=" * 72)
        print("测试结束。")
        print("=" * 72)
    except Exception:  # noqa: BLE001
        print("\n[ERROR] 子图运行失败，定位信息如下：")
        traceback.print_exc()
        print(
            "\n常见原因与排查：\n"
            "  1. 未安装依赖：pip install -r backend/requirements.txt\n"
            "  2. 缺少 API Key：检查 backend/.env 中的 OPENAI_API_KEY / TAVILY_API_KEY / DASHSCOPE_API_KEY\n"
            "  3. 未安装 reranker：pip install sentence-transformers\n"
            "  4. 本地知识库为空（仅影响 document 模式）：先调用 process_documents 建立 ChromaDB\n"
            "  5. 运行位置：在 backend/ 目录下执行，或使用 `python -m app.graph.nodes.researcher`"
        )
        sys.exit(1)

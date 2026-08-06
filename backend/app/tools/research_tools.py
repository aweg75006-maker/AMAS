from __future__ import annotations

import json
from typing import Any

from app.rag.engine import get_candidate_documents, get_retriever
from app.tools.registry import ToolContext, ToolRegistry, ToolSpec
from app.tools.search import search_tavily, search_tavily_candidates
from app.utils.llm import get_llm


def register_research_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="rag.retrieve",
            handler=_rag_retrieve,
            description="Retrieve relevant local knowledge-base documents.",
            input_schema="query:string, knowledge_base_id:string",
            output_schema="documents:list",
            tags=("rag", "knowledge_base"),
        )
    )
    registry.register(
        ToolSpec(
            name="rag.retrieve_candidates",
            handler=_rag_retrieve_candidates,
            description="Retrieve wide local knowledge-base candidates before global reranking.",
            input_schema="query:string, knowledge_base_id:string",
            output_schema="documents:list",
            tags=("rag", "knowledge_base", "candidates"),
        )
    )
    registry.register(
        ToolSpec(
            name="rag.relevance_grade",
            handler=_rag_relevance_grade,
            description="Assess evidence coverage and propose follow-up retrieval queries.",
            input_schema="query:string, document_context:string",
            output_schema="sufficient:boolean, coverage_gap:string, follow_up_queries:list[string]",
            tags=("rag", "llm", "grader"),
        )
    )
    registry.register(
        ToolSpec(
            name="web.retrieve_candidates",
            handler=_web_retrieve_candidates,
            description="Search the public web and preserve source metadata for global reranking.",
            input_schema="query:string",
            output_schema="candidates:list",
            tags=("web", "search", "candidates"),
        )
    )
    registry.register(
        ToolSpec(
            name="web.search",
            handler=_web_search,
            description="Search the public web and return compact text context.",
            input_schema="query:string",
            output_schema="content:string",
            tags=("web", "search"),
        )
    )


def _rag_retrieve(payload: dict[str, Any], context: ToolContext):
    query = payload["query"]
    knowledge_base_id = payload.get("knowledge_base_id", "kb_default")
    retriever = get_retriever(knowledge_base_id=knowledge_base_id)
    if retriever is None:
        return []
    return retriever.invoke(query)


def _rag_retrieve_candidates(payload: dict[str, Any], context: ToolContext):
    return get_candidate_documents(
        payload["query"],
        knowledge_base_id=payload.get("knowledge_base_id", "kb_default"),
    )


def _rag_relevance_grade(payload: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    query = payload["query"]
    raw_context = payload.get("document_context", "")
    grader_prompt = f"""
    你是一个严格的 RAG 证据评估员。
    
    用户问题: {query}
    检索到的文档片段: 
    {raw_context[:2000]} (截取部分)
    
    请判断这些证据能否完整、可靠地回答问题，并且只输出 JSON：
    {{
      "sufficient": true,
      "coverage_gap": "",
      "follow_up_queries": []
    }}

    若证据不足，设置 sufficient=false，写出具体 coverage_gap，
    并提供 1 到 3 条可直接用于搜索引擎的 follow_up_queries。
    不要使用 Markdown 代码块，不要输出 JSON 之外的内容。
    """
    from app.utils.budget_enforcer import create_enforcer_from_state

    enforcer = create_enforcer_from_state(dict(context.state))
    response, _ = enforcer.wrap_llm_call(
        "researcher",
        get_llm(model_type="smart"),
        grader_prompt,
        dict(context.state),
    )
    return _parse_evidence_assessment(response.content)


def _parse_evidence_assessment(content: str) -> dict[str, Any]:
    """Normalize an LLM assessment without allowing malformed output into retrieval."""
    raw = (content or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "sufficient": "YES" in raw.upper(),
            "coverage_gap": "评估结果格式无效，无法确定证据缺口",
            "follow_up_queries": [],
        }
    if not isinstance(payload, dict):
        return {
            "sufficient": False,
            "coverage_gap": "评估结果不是 JSON 对象，无法确定证据缺口",
            "follow_up_queries": [],
        }

    queries = payload.get("follow_up_queries", [])
    if not isinstance(queries, list):
        queries = []
    normalized = []
    for query in queries:
        value = " ".join(str(query).split())
        if value and value not in normalized:
            normalized.append(value[:180])
        if len(normalized) == 3:
            break
    return {
        "sufficient": payload.get("sufficient") is True
        or str(payload.get("sufficient", "")).strip().lower() == "true",
        "coverage_gap": str(payload.get("coverage_gap", "")).strip()[:500],
        "follow_up_queries": normalized,
    }


def _web_search(payload: dict[str, Any], context: ToolContext) -> str:
    return search_tavily(payload["query"])


def _web_retrieve_candidates(payload: dict[str, Any], context: ToolContext) -> list[dict[str, object]]:
    return search_tavily_candidates(payload["query"])

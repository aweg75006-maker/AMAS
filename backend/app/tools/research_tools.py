from __future__ import annotations

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
            description="Judge whether retrieved local documents are relevant.",
            input_schema="query:string, document_context:string",
            output_schema="grade:YES|NO",
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


def _rag_relevance_grade(payload: dict[str, Any], context: ToolContext) -> str:
    query = payload["query"]
    raw_context = payload.get("document_context", "")
    grader_prompt = f"""
    你是一个严格的文档相关性评估员。
    
    用户问题: {query}
    检索到的文档片段: 
    {raw_context[:2000]} (截取部分)
    
    请判断：这些文档片段是否包含回答用户问题所需的信息？
    - 如果文档完全不相关（例如问'吃什么'但文档是'深度学习'），请回答 "NO"。
    - 如果文档相关或部分相关，请回答 "YES"。
    
    只输出 "YES" 或 "NO"，不要输出其他内容。
    """
    from app.utils.budget_enforcer import create_enforcer_from_state

    enforcer = create_enforcer_from_state(dict(context.state))
    response, _ = enforcer.wrap_llm_call(
        "researcher",
        get_llm(model_type="smart"),
        grader_prompt,
        dict(context.state),
    )
    return response.content.strip().upper()


def _web_search(payload: dict[str, Any], context: ToolContext) -> str:
    return search_tavily(payload["query"])


def _web_retrieve_candidates(payload: dict[str, Any], context: ToolContext) -> list[dict[str, object]]:
    return search_tavily_candidates(payload["query"])

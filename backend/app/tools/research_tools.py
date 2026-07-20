from __future__ import annotations

from typing import Any

from app.rag.engine import get_retriever
from app.tools.registry import ToolContext, ToolRegistry, ToolSpec
from app.tools.search import search_tavily
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
            name="web.search",
            handler=_web_search,
            description="Search the public web and return compact text context.",
            input_schema="query:string",
            output_schema="content:string",
            tags=("web", "search"),
        )
    )
    registry.register(
        ToolSpec(
            name="delegate_to_connector",
            handler=_delegate_to_connector,
            description=(
                "把子问题委派给注册的第三方 Agent connector（如 internal_subagent "
                "或外部 HTTP Agent 端点），回收结果用于研究。失败或 connector 不存在时"
                "返回可读错误文本，不中断主流程。"
            ),
            input_schema="connector:string, prompt:string, system_prompt:string?",
            output_schema="content:string",
            tags=("agent", "connector", "delegation"),
        )
    )


def _rag_retrieve(payload: dict[str, Any], context: ToolContext):
    query = payload["query"]
    knowledge_base_id = payload.get("knowledge_base_id", "kb_default")
    retriever = get_retriever(knowledge_base_id=knowledge_base_id)
    if retriever is None:
        return []
    return retriever.invoke(query)


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


def _delegate_to_connector(payload: dict[str, Any], context: ToolContext) -> str:
    """工具层桥接：把子问题委派给 ConnectorRegistry 中的第三方 Agent。

    用 ``connector.run(...)``（同步入口，内部独立线程跑事件循环）调用异步 Connector，
    兼容工具运行时在线程中执行的既有模式。连接器返回的 ConnectorResult 失败时会
    降级为可读错误文本，保证主研究流程不中断。
    """
    name = payload.get("connector") or payload.get("connector_name")
    prompt = payload.get("prompt")
    system_prompt = payload.get("system_prompt")
    if not name or not prompt:
        return "[delegate_to_connector] 需要 connector 名称与 prompt。"

    from app.connectors.base import ConnectorContext
    from app.connectors.registry import get_connector_registry

    registry = get_connector_registry()
    if not registry.has(name):
        return (
            f"[delegate_to_connector] 未找到 connector: {name}；"
            f"已注册：{registry.names()}"
        )

    connector = registry.get(name)
    result = connector.run(
        prompt,
        context=ConnectorContext(
            node_name=context.node_name,
            state=context.state,
            session_id=str(context.state.get("session_id", "")),
            request_id=str(context.state.get("request_id", "")),
        ),
        system_prompt=system_prompt,
    )
    return result.to_text()

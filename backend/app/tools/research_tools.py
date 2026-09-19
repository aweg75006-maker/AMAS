"""研究类工具集：RAG 检索与网络搜索的统一封装。

本模块把"检索能力"注册成可供图节点调用的工具：
- rag.retrieve_candidates   : 本地知识库广召回（稠密向量 + BM25 双通道），供全局重排前取候选；
- rag.retrieve              : 本地知识库直接检索（按 query 返回文档）；
- rag.relevance_grade       : LLM 证据评估——判断证据是否充分、缺什么、建议补搜关键词；
- web.retrieve_candidates   : 联网搜索，保留来源元数据供统一重排；
- web.search                : 联网搜索，直接返回精简文本上下文。

工具只做"取数"，决策（是否重排、是否迭代检索）由图节点负责。
"""

from __future__ import annotations

import json
from typing import Any

from app.rag.engine import get_candidate_documents, get_retriever
from app.tools.registry import ToolContext, ToolRegistry, ToolSpec
from app.tools.schemas import RagRelevanceGradeIn, RagRetrieveIn, WebSearchIn
from app.tools.search import search_tavily, search_tavily_candidates
from app.utils.llm import get_llm


def register_research_tools(registry: ToolRegistry) -> None:
    """把研究类工具注册进指定注册表（幂等，供全局注册表初始化调用）。

    每条注册声明都带三类信息，各自的作用：
    - ``input_schema`` / ``output_schema``：给人看的说明字符串，同时被 Harness manifest 对照；
    - ``params``：机器可校验的参数模型（S1 新增），驱动服务端校验 + LLM function schema；
    - ``server_filled``：服务端注入参数（S1 声明，S2 生效），从 function schema 里剔除，
      模型看不到、也不许传。
    """
    registry.register(
        ToolSpec(
            name="rag.retrieve",
            handler=_rag_retrieve,
            description="Retrieve relevant local knowledge-base documents.",
            # 字符串说明保留：Harness manifest 要对照、人也需要一眼看懂参数
            input_schema="query:string, knowledge_base_id:string",
            output_schema="documents:list",
            tags=("rag", "knowledge_base"),
            # 机器校验用的模型：只声明 query，knowledge_base_id 走下面的 server_filled
            params=RagRetrieveIn,
            server_filled=("knowledge_base_id",),
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
            # 入参形状与 rag.retrieve 完全一致，复用同一个模型
            params=RagRetrieveIn,
            server_filled=("knowledge_base_id",),
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
            # 这个工具的入参完全由 Researcher 节点内部构造，没有服务端注入参数
            params=RagRelevanceGradeIn,
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
            params=WebSearchIn,
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
            params=WebSearchIn,
        )
    )


def _rag_retrieve(payload: dict[str, Any], context: ToolContext):
    """本地知识库直接检索：返回最相关的文档（用于"仅文档"等需要精确结果的场景）。

    关于 ``knowledge_base_id``（S2）：
    该字段已在 ``ToolSpec.server_filled`` 中声明，正常情况下由 ``ToolRuntime``
    从图状态注入到 payload 里，模型在 function schema 中看不到它。

    这里仍然用 ``payload.get(...) or "kb_default"`` 兜底，**不能改成
    ``payload["knowledge_base_id"]``** —— 因为存在绕过 runtime 的直接调用路径
    （例如测试里注册假 handler、或别处直接复用这个函数），
    改成硬取值会让这些路径抛 KeyError。
    """
    query = payload["query"]
    knowledge_base_id = payload.get("knowledge_base_id", "kb_default")
    retriever = get_retriever(knowledge_base_id=knowledge_base_id)
    if retriever is None:
        # 知识库不存在或未初始化：返回空列表而非抛错，让上层走降级逻辑
        return []
    return retriever.invoke(query)


def _rag_retrieve_candidates(payload: dict[str, Any], context: ToolContext):
    """本地知识库广召回：稠密 + BM25 双通道取候选，交给后续全局重排（取 top-k）。

    ``knowledge_base_id`` 的处理方式与 ``_rag_retrieve`` 一致：runtime 负责注入，
    这里保留默认值兜底以兼容直接调用路径。
    """
    return get_candidate_documents(
        payload["query"],
        knowledge_base_id=payload.get("knowledge_base_id", "kb_default"),
    )


def _rag_relevance_grade(payload: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """LLM 证据评估：判断检索到的文档是否足以回答问题。

    返回结构化评估（sufficient / coverage_gap / follow_up_queries），
    供 Researcher 子图决定：证据够了就进 Writer，不够就带着补搜关键词重新检索。
    """
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

    # 评估走预算护栏：用当前节点的预算状态包裹 LLM 调用，超预算按策略处理
    enforcer = create_enforcer_from_state(dict(context.state))
    response, _ = enforcer.wrap_llm_call(
        "researcher",
        get_llm(model_type="smart"),  # 评估用强推理模型（smart），判断准确率更高
        grader_prompt,
        dict(context.state),
    )
    return _parse_evidence_assessment(response.content)


def _parse_evidence_assessment(content: str) -> dict[str, Any]:
    """解析 LLM 的评估结果，并做防御性规范化——绝不把格式错误的输出放进检索决策。

    兜底策略：
    - 无法解析为 JSON 时，用"文本里是否含 YES"粗略判断是否充分；
    - follow_up_queries 逐个清洗去重、限长、最多 3 条。
    """
    raw = (content or "").strip()
    if raw.startswith("```"):
        # 容忍模型用 Markdown 代码块包裹 JSON
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

    # 规范化补搜关键词：去空白、去重、截断到 180 字符、最多 3 条
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
    """联网搜索：返回拼接的纯文本内容（省 token，供节点直接当上下文用）。"""
    return search_tavily(payload["query"])


def _web_retrieve_candidates(payload: dict[str, Any], context: ToolContext) -> list[dict[str, object]]:
    """联网搜索：返回带来源元数据的候选（供统一去重 + 全局重排）。"""
    return search_tavily_candidates(payload["query"])

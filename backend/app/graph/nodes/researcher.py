from app.core.logging import get_logger
from app.graph.policies.researcher_policy import ResearcherPolicy
from app.graph.state import AgentState
from app.tools.runtime import ToolRuntime

logger = get_logger("iris.graph.researcher")


def _append_tool_run(tool_runs: list[dict], result) -> None:
    if result.run is not None:
        tool_runs.append(result.run.to_dict())


def research_node(state: AgentState):

    mode = state.get("search_mode", "hybrid")
    knowledge_base_id = state.get("knowledge_base_id", "kb_default")
    query = state["query"]
    plans = state["plan"]
    results = []
    tool_runs = []
    tool_runtime = ToolRuntime(node_name="researcher")
    policy = ResearcherPolicy()

    logger.info(
        "researcher_started",
        extra={
            "search_mode": mode,
            "knowledge_base_id": knowledge_base_id,
            "query_length": len(query),
            "plan_count": len(plans),
        },
    )
    
    rag_content = ""
    is_doc_relevant = False
    
    logger.info("rag_retrieval_started")
    retrieve_result = tool_runtime.run_registered(
        "rag.retrieve",
        {
            "query": query,
            "knowledge_base_id": knowledge_base_id,
        },
        state=state,
        input_summary=query,
        metadata={"knowledge_base_id": knowledge_base_id},
    )
    _append_tool_run(tool_runs, retrieve_result)
    if retrieve_result.ok:
        docs = retrieve_result.value
        retrieval_decision = policy.decide_after_retrieval(docs)
        if retrieval_decision.should_grade:
            raw_context = "\n\n".join([f"[文档片段]: {doc.page_content}" for doc in docs])
            logger.info(
                "rag_relevance_grading_started",
                extra={"doc_count": len(docs), "raw_context_length": len(raw_context)},
            )
            grade_result = tool_runtime.run_registered(
                "rag.relevance_grade",
                {
                    "query": query,
                    "document_context": raw_context,
                },
                state=state,
                input_summary=f"{query}\n{raw_context[:500]}",
                metadata={
                    "knowledge_base_id": knowledge_base_id,
                    "doc_count": len(docs),
                    "raw_context_length": len(raw_context),
                },
            )
            _append_tool_run(tool_runs, grade_result)
            grade = grade_result.value if grade_result.ok else "NO"
            grade_decision = policy.decide_after_grade(grade, grade_ok=grade_result.ok)
            is_doc_relevant = grade_decision.is_relevant
            if grade_decision.should_use_documents:
                rag_content = "\n\n".join([f"[文档片段]: {doc.page_content}" for doc in docs])
                results.append(f"### 📂 本地文档资料 (已核实相关)\n{rag_content}\n")
                logger.info("rag_relevance_passed", extra={"grade": grade})
            else:
                logger.warning("rag_relevance_failed", extra={"grade": grade})

                if grade_decision.message:
                    results.append(grade_decision.message)
        else:
            logger.info("rag_no_documents_found")
    else:
        logger.warning(
            "rag_retrieval_failed",
            extra={
                "error_code": retrieve_result.run.error_code if retrieve_result.run else "",
                "error_message": retrieve_result.run.error_message if retrieve_result.run else "",
            },
        )
    
    post_rag_decision = policy.decide_after_rag(
        search_mode=mode,
        is_doc_relevant=is_doc_relevant,
    )
    if post_rag_decision.log_event:
        if post_rag_decision.should_stop:
            logger.warning(post_rag_decision.log_event)
        else:
            logger.info(post_rag_decision.log_event)
    if post_rag_decision.message:
        results.append(post_rag_decision.message)
    if post_rag_decision.should_stop:
        logger.info(
            "researcher_completed",
            extra={"result_count": len(results), "should_stop": True},
        )
        return {
            "search_results": results,
            "should_stop": True,
            "_tool_runs": tool_runs,
        }

    if post_rag_decision.should_web_search:
        logger.info("web_search_started", extra={"plan_count": len(plans)})
        for q in plans:
            search_result = tool_runtime.run_registered(
                "web.search",
                {"query": q},
                state=state,
                input_summary=q,
                metadata={"query_length": len(q)},
            )
            _append_tool_run(tool_runs, search_result)
            if search_result.ok:
                content = search_result.value
                results.append(f"### 🌐 网络搜索结果 ({q})\n{content}\n")
            else:
                logger.warning(
                    "web_search_failed",
                    extra={
                        "query_length": len(q),
                        "error_code": search_result.run.error_code if search_result.run else "",
                        "error_message": search_result.run.error_message if search_result.run else "",
                    },
                )
            
    logger.info(
        "researcher_completed",
        extra={"result_count": len(results), "should_stop": False},
    )
    return {"search_results": results, "_tool_runs": tool_runs}

# 测试
# def test():
#     state:AgentState = {
#         'query':'Transformer',
#         'plan':['Transformer发展历程','Transformer原理'],
#         'search_mode':'hybird'
#     }
#     res = research_node(state)
#     print(res)
# test()

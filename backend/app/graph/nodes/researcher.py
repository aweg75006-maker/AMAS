from app.core.logging import get_logger
from app.tools.search import search_tavily
from app.graph.state import AgentState
from app.rag.engine import get_retriever
from app.utils.llm import get_llm

logger = get_logger("iris.graph.researcher")

def research_node(state: AgentState):

    mode = state.get("search_mode", "hybrid")
    query = state["query"]
    plans = state["plan"]
    results = []

    logger.info(
        "researcher_started",
        extra={"search_mode": mode, "query_length": len(query), "plan_count": len(plans)},
    )
    
    retriever = get_retriever()
    rag_content = ""
    is_doc_relevant = False
    
    if retriever:
        logger.info("rag_retrieval_started")
        try:
            docs = retriever.invoke(query)
            if docs:
                raw_context = "\n\n".join([f"[文档片段]: {doc.page_content}" for doc in docs])
                logger.info(
                    "rag_relevance_grading_started",
                    extra={"doc_count": len(docs), "raw_context_length": len(raw_context)},
                )
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
                # Phase 4: 预算执行（文档相关性审计）
                from app.utils.budget_enforcer import create_enforcer_from_state
                enforcer = create_enforcer_from_state(state)
                response, _ = enforcer.wrap_llm_call(
                    "researcher", get_llm(model_type="smart"), grader_prompt, state
                )
                grade = response.content.strip().upper()
                if "YES" in grade:
                    is_doc_relevant = True
                    rag_content = "\n\n".join([f"[文档片段]: {doc.page_content}" for doc in docs])
                    results.append(f"### 📂 本地文档资料 (已核实相关)\n{rag_content}\n")
                    logger.info("rag_relevance_passed", extra={"grade": grade})
                else:
                    logger.warning("rag_relevance_failed", extra={"grade": grade})

                    results.append(f"[系统提示]: 检索了本地文档，但发现内容与问题不相关，已自动忽略。")
            else:
                logger.info("rag_no_documents_found")
        except Exception as e:
            logger.exception("rag_retrieval_failed")
    else:
        logger.info("rag_retriever_empty")
    
    if mode == "document":
        if is_doc_relevant:
            logger.info("document_only_relevant")
        else:
            logger.warning("document_only_irrelevant")
            results.append("【严重警告】：用户选择了 Document Only 模式，但上传的文档与问题完全无关。请直接在报告中诚实地告诉用户：“您上传的文档中没有关于此问题的说明”，不要编造答案。")
            logger.info(
                "researcher_completed",
                extra={"result_count": len(results), "should_stop": True},
            )
            return {
                "search_results": results,
                "should_stop": True 
            }


    else: 
        should_web_search = True
        
        if is_doc_relevant:

            logger.info("hybrid_doc_relevant")
        else:

            logger.warning("hybrid_doc_irrelevant_auto_web")

        if should_web_search:
            logger.info("web_search_started", extra={"plan_count": len(plans)})
            for q in plans:
                try:
                    content = search_tavily(q)
                    results.append(f"### 🌐 网络搜索结果 ({q})\n{content}\n")
                except Exception as e:
                    logger.exception("web_search_failed", extra={"query_length": len(q)})
            
    logger.info(
        "researcher_completed",
        extra={"result_count": len(results), "should_stop": False},
    )
    return {"search_results": results}

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

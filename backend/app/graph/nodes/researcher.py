from langchain_core.messages import HumanMessage
from app.tools.search import search_tavily
from app.graph.state import AgentState
from app.rag.engine import get_retriever
from app.utils.llm import get_llm

llm = get_llm(model_type="smart")
def research_node(state: AgentState):

    mode = state.get("search_mode", "hybrid")
    query = state["query"]
    plans = state["plan"]
    results = []

    print(f"--- [Researcher] 开始搜索 | 模式: {mode} ---")
    
    retriever = get_retriever()
    rag_content = ""
    is_doc_relevant = False
    
    if retriever:
        print("--- [RAG] 正在检索本地知识库... ---")
        try:
            docs = retriever.invoke(query)
            if docs:
                raw_context = "\n\n".join([f"[文档片段]: {doc.page_content}" for doc in docs])
                print("--- [RAG] 正在进行文档相关性审计... ---")
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
                grade = llm.invoke([HumanMessage(content=grader_prompt)]).content.strip().upper()
                if "YES" in grade:
                    is_doc_relevant = True
                    rag_content = "\n\n".join([f"[文档片段]: {doc.page_content}" for doc in docs])
                    results.append(f"### 📂 本地文档资料 (已核实相关)\n{rag_content}\n")
                    print("--- [RAG] ✅ 文档通过相关性审计 ---")
                else:
                    print(f"--- [RAG] ⚠️ 警告：文档内容与问题 '{query}' 不相关，已自动忽略 ---")

                    results.append(f"[系统提示]: 检索了本地文档，但发现内容与问题不相关，已自动忽略。")
            else:
                print("--- [RAG] 未找到相关内容 ---")
        except Exception as e:
            print(f"--- [RAG] 检索出错: {e} ---")
    else:
        print("--- [RAG] 知识库为空，跳过 ---")
    
    if mode == "document":
        if is_doc_relevant:
            print("--- [策略] 文档相关，按计划仅使用文档 ---")
        else:
            print("--- [策略] 文档不相关，但这又是 Document Only 模式 ---")
            print("[WARNING] 文档内容与问题不匹配，无法生成有效回答") 
            results.append("【严重警告】：用户选择了 Document Only 模式，但上传的文档与问题完全无关。请直接在报告中诚实地告诉用户：“您上传的文档中没有关于此问题的说明”，不要编造答案。")
            return {
                "search_results": results,
                "should_stop": True 
            }


    else: 
        should_web_search = True
        
        if is_doc_relevant:

            print("--- [策略] 文档相关，启用混合增强模式 (Doc + Web) ---")
        else:

            print("--- [策略] 文档不相关，自动切换为全网搜索模式 (Auto-Web) ---")
            print("[WARNING] 本地文档与问题无关，系统已自动切换为全网搜索") # 触发前端弹窗

        if should_web_search:
            print("--- [Web] 正在执行互联网搜索... ---")
            for q in plans:
                try:
                    content = search_tavily(q)
                    results.append(f"### 🌐 网络搜索结果 ({q})\n{content}\n")
                except Exception as e:
                    print(f"--- [Web] 搜索 {q} 失败: {e} ---")
            
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
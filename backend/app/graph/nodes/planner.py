from langchain_core.prompts import ChatPromptTemplate
from app.utils.llm import get_llm
from app.graph.state import AgentState

llm = get_llm()


PLAN_PROMPT = ChatPromptTemplate.from_template(
    """你是一个专业的调研助手。
    针对用户的问题：{query}
    请生成 3-5 个简短的搜索子问题，用于在 Google 上查找相关信息。
    已有审查意见（如果有）：{critique}
    如果存在审查意见，请务必针对意见中提到的缺失信息生成关键词。

    历史研究脉络（之前已经研究过的方向和结论）：
    {memory_context}

    如果历史研究中有与当前问题相关的内容，请利用已有知识规划搜索方向，避免重复搜索已研究透彻的子问题。
    只返回关键词，用逗号分隔，不要有其他废话。
    例如：子问题1, 子问题2, 子问题3
    """
)

def plan_node(state: AgentState):
    print("--- [节点] 正在规划搜索路径 ---")
    query = state["query"]
    critique = state.get("critique", "")

    # Phase 2: 注入跨轮记忆上下文
    memory_context = state.get("memory_context", "")
    if not memory_context:
        episodic = state.get("episodic_memory", [])
        if episodic:
            parts = ["之前研究过的方向："]
            for turn in episodic[-3:]:
                plan = turn.get("plan", [])
                if plan:
                    parts.append(f"- {', '.join(plan[:3])}")
            memory_context = "\n".join(parts)
        else:
            memory_context = "（这是第一个研究任务，无历史脉络）"

    response = llm.invoke(PLAN_PROMPT.format(
        query=query,
        critique=critique,
        memory_context=memory_context,
    ))
    plans = [p.strip() for p in response.content.split(",")]
    return {"plan": plans}

# def test():
#     state:AgentState={
#         "query":"Transformer发展现状"
#     }
#     print(plan_node(state))

# python -m app.graph.nodes.planner
# test()
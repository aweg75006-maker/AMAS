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
    只返回关键词，用逗号分隔，不要有其他废话。
    例如：子问题1, 子问题2, 子问题3
    """
)

def plan_node(state: AgentState):
    print("--- [节点] 正在规划搜索路径 ---")
    query = state["query"]
    critique = state.get("critique", "") 
    response = llm.invoke(PLAN_PROMPT.format(query=query, critique=critique))
    plans = [p.strip() for p in response.content.split(",")]
    return {"plan": plans}

# def test():
#     state:AgentState={
#         "query":"Transformer发展现状"
#     }
#     print(plan_node(state))

# python -m app.graph.nodes.planner
# test()
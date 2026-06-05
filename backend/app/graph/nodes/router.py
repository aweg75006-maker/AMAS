from langchain_core.messages import HumanMessage
from app.graph.state import AgentState
from app.utils.llm import get_llm

# 用一个小模型即可，速度快
router_llm = get_llm()

# 兜底策略，防止模型抽疯不按要求输出
def looks_like_refine(q: str) -> bool:
    q = q.strip()
    refine_triggers = ["改", "润色", "优化", "补充", "扩写", "写详细", "更通俗", "更正式", "重写", "调整", "删", "加", "第", "章", "段", "标题", "格式", "总结", "结论", "引用"]
    return any(t in q for t in refine_triggers)

def route_query(state: AgentState):
    """
    判断用户输入是“新查询”还是“修改指令”
    """
    query = state["query"]
    has_report = bool(state.get("final_report", "").strip())

    print(f"--- [Router] 正在分析意图: '{query}' (已有报告: {has_report}) ---")

    if not has_report:
        return "planner"
    final_report = state["final_report"]
    report = final_report[:50]

    prompt = f"""
    当前系统已经生成了一份研究报告。
    用户的最新输入是: "{query}"。
    用户最近一次生成的报告片段是："{report}"
    
    请判断用户的意图：
    1. "NEW_TOPIC": 用户想要开始一个全新的研究课题（例如："帮我查一下量子计算"）。
    2. "REFINE": 用户想要基于现有的报告进行修改、润色或补充（例如："第一章写详细点"、"改通俗点"）。
    
    只输出 "NEW_TOPIC" 或 "REFINE"。
    """
    
    result = router_llm.invoke([HumanMessage(content=prompt)]).content.strip().upper()
    print(f"--- [Router] LLM 判定结果: {result} ---")
    
    if result == "REFINE":
        return "refiner"  # 去专门的修改节点
    if result == "NEW_TOPIC":
        return "planner"  # 开启新课题
    # 兜底：模型没按要求输出
    print(f"--- [Router][WARN] 非法输出: {result!r}，启用兜底规则 ---")
    return "refiner" if looks_like_refine(query) else "planner"

# def test():
#     state:AgentState={
#         "query":"写详细一点",
#         "final_report": "Transformer发展"
#     }
#     print(route_query(state))

# python -m app.graph.nodes.router
# test()
# print(looks_like_refine("将第一段改的更通俗"))

# 流式输出
# res = router_llm.stream([HumanMessage(content='你是谁')])
# for chunk in res:
#     print(chunk.content, end='', flush=True)
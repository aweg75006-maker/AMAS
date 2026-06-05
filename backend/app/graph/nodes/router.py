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


def _find_latest_report(state: AgentState) -> str:
    """
    查找最近的报告——先在当前 state 中查，再在跨轮记忆中查。

    Phase 2: 支持从 episodic_memory 中获取上一个 Turn 的报告，
    使得跨页面刷新后仍能正确处理 REFINE 意图。
    """
    # 1) 当前状态中的报告（同一请求内）
    current = state.get("final_report", "").strip()
    if current:
        return current

    # 2) 跨轮记忆中的最新报告（上一个 Turn）
    episodic = state.get("episodic_memory", [])
    if episodic:
        latest = episodic[-1]
        return latest.get("final_report", "")

    return ""


def route_query(state: AgentState):
    """
    判断用户输入是"新查询"还是"修改指令"。

    Phase 2: 支持跨 Turn REFINE——当当前请求无报告但历史中有时，
    仍能识别 REFINE 意图并路由到 refiner。
    """
    query = state["query"]
    final_report = _find_latest_report(state)
    has_report = bool(final_report)

    # Phase 2: 检查是否有历史研究脉络
    turn_number = state.get("turn_number", 1)
    episodic_count = len(state.get("episodic_memory", []))

    print(
        f"--- [Router] 正在分析意图: '{query[:80]}' "
        f"(已有报告: {has_report}, Turn #{turn_number}, "
        f"历史记忆: {episodic_count} turns) ---"
    )

    # 既没有当前报告也没有历史报告 → 一定是新课题
    if not has_report:
        return "planner"

    # 有报告（当前或历史），让 LLM 判断
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

    # Phase 4: 预算执行
    from app.utils.budget_enforcer import create_enforcer_from_state
    enforcer = create_enforcer_from_state(state)
    response, _ = enforcer.wrap_llm_call(
        "router", router_llm, prompt, state
    )
    result = response.content.strip().upper()
    print(f"--- [Router] LLM 判定结果: {result} ---")

    if result == "REFINE":
        return "refiner"
    if result == "NEW_TOPIC":
        return "planner"
    # 兜底：模型没按要求输出
    print(f"--- [Router][WARN] 非法输出: {result!r}，启用兜底规则 ---")
    return "refiner" if looks_like_refine(query) else "planner"

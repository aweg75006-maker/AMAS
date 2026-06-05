from langchain_core.messages import HumanMessage
from app.graph.state import AgentState
from app.utils.llm import get_llm

llm = get_llm()

def _find_latest_report(state: AgentState) -> str:
    """查找最近的报告——当前 state 或跨轮记忆。"""
    current = state.get("final_report", "").strip()
    if current:
        return current
    episodic = state.get("episodic_memory", [])
    if episodic:
        return episodic[-1].get("final_report", "")
    return ""


def refine_node(state: AgentState):
    query = state["query"]               # 修改指令，例如 "把第一章改详细点"
    old_report = _find_latest_report(state)

    print(f"--- [Refiner] 正在根据指令修改报告: {query} ---")

    # Phase 2: 注入跨轮记忆上下文
    memory_context = state.get("memory_context", "")
    if not memory_context:
        episodic = state.get("episodic_memory", [])
        if episodic:
            parts = ["## 历史研究脉络"]
            for turn in episodic[-3:]:
                parts.append(
                    f"- Turn {turn.get('turn_number', '?')}: "
                    f"{turn.get('query', '')[:150]}"
                )
            memory_context = "\n".join(parts)
        else:
            memory_context = "（无历史研究记录）"

    prompt = f"""
    你是一个专业的报告编辑。

    【历史研究脉络】
    {memory_context}

    【原始报告】
    {old_report}

    【用户修改指令】
    {query}

    请根据用户的指令，对原始报告进行修改。
    注意：
    1. 保持原有的 Markdown 结构。
    2. 只修改用户要求的部分，其余部分尽量保持原汁原味。
    3. 如果指令涉及引用之前的研究，请参考上述历史研究脉络。
    4. 直接输出修改后的完整报告，不要有任何前言后语。
    """

    response = llm.invoke([HumanMessage(content=prompt)])
    new_report = response.content

    return {
        "final_report": new_report,
        "review_status": "PASS" # 修改后默认通过，直接给用户看
    }
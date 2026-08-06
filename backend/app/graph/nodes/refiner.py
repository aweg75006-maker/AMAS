from app.core.logging import get_logger
from app.graph.state import AgentState
from app.harness.registry import get_harness_node, get_prompt_template
from app.utils.llm import get_llm

logger = get_logger("iris.graph.refiner")

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
    if state.get("human_input"):
        query = f"{query}\n人工补充：{state['human_input']}"
    old_report = _find_latest_report(state)

    logger.info(
        "refiner_started",
        extra={"query_length": len(query), "old_report_length": len(old_report)},
    )

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

    harness_node = get_harness_node("refiner")
    prompt = get_prompt_template(harness_node.prompt_id).format(
        memory_context=memory_context,
        old_report=old_report,
        query=query,
    )

    # Phase 4: 预算执行
    from app.utils.budget_enforcer import create_enforcer_from_state
    enforcer = create_enforcer_from_state(state)
    response, _ = enforcer.wrap_llm_call("refiner", get_llm(), prompt, state)
    new_report = response.content
    logger.info("refiner_completed", extra={"new_report_length": len(new_report)})

    return {
        "final_report": new_report,
        "review_status": "PASS" # 修改后默认通过，直接给用户看
    }

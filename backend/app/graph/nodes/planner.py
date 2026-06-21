from app.core.logging import get_logger
from app.harness.registry import get_harness_node, get_prompt_template
from app.utils.llm import get_llm
from app.graph.state import AgentState

logger = get_logger("iris.graph.planner")

def plan_node(state: AgentState):
    query = state["query"]
    critique = state.get("critique", "")
    logger.info(
        "planner_started",
        extra={"query_length": len(query), "critique_length": len(critique)},
    )

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

    # Phase 4: 预算执行
    from app.utils.budget_enforcer import create_enforcer_from_state
    enforcer = create_enforcer_from_state(state)
    harness_node = get_harness_node("planner")
    prompt_text = get_prompt_template(harness_node.prompt_id).format(
        query=query, critique=critique, memory_context=memory_context,
    )
    response, _ = enforcer.wrap_llm_call("planner", get_llm(), prompt_text, state)

    plans = [p.strip() for p in response.content.split(",")]
    logger.info("planner_completed", extra={"plan_count": len(plans)})
    return {"plan": plans}

# def test():
#     state:AgentState={
#         "query":"Transformer发展现状"
#     }
#     print(plan_node(state))

# python -m app.graph.nodes.planner
# test()

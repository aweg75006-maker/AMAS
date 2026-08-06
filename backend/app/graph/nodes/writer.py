from app.core.logging import get_logger
from app.harness.registry import get_harness_node, get_prompt_template
from app.utils.llm import get_llm
from app.graph.state import AgentState

logger = get_logger("iris.graph.writer")

def write_node(state: AgentState):
    query = state["query"]
    content = "\n\n".join(state["search_results"])
    logger.info(
        "writer_started",
        extra={
            "query_length": len(query),
            "search_result_count": len(state.get("search_results", [])),
            "content_length": len(content),
        },
    )

    critique = state.get("critique", "")
    critique_section = ""
    if critique:
        critique_section = f"""
        【重要提示】上一版本的报告未通过审查。
        审查意见如下："{critique}"
        请务必在本次写作中修正上述问题。
        """
    human_input = state.get("human_input", "").strip()
    if human_input:
        critique_section += f"\n【人工补充要求】{human_input}\n"

    # Phase 2: 注入跨轮记忆上下文
    memory_context = state.get("memory_context", "")
    if not memory_context:
        # 如果没有装配好的上下文，从 episodic_memory 构建简易版本
        episodic = state.get("episodic_memory", [])
        if episodic:
            parts = ["## 历史研究记录\n"]
            for turn in episodic[-3:]:  # 最多 3 个
                parts.append(
                    f"- **Turn {turn.get('turn_number', '?')}**: "
                    f"{turn.get('query', '')[:150]}"
                )
                report = turn.get("final_report", "")
                if report:
                    parts.append(f"  结论: {report[-200:]}")
            memory_context = "\n".join(parts)

    # Phase 4: 预算执行
    from app.utils.budget_enforcer import create_enforcer_from_state
    enforcer = create_enforcer_from_state(state)
    harness_node = get_harness_node("writer")
    prompt_text = get_prompt_template(harness_node.prompt_id).format(
        query=query,
        content=content,
        critique_section=critique_section,
        memory_context=memory_context,
    )
    response, _ = enforcer.wrap_llm_call("writer", get_llm(), prompt_text, state)

    logger.info("writer_completed", extra={"report_length": len(response.content)})
    return {"final_report": response.content}

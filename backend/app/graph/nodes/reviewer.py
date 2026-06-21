import json
from langchain_core.prompts import ChatPromptTemplate
from app.core.logging import get_logger
from app.utils.llm import get_llm
from app.graph.state import AgentState

logger = get_logger("iris.graph.reviewer")


REVIEW_PROMPT = ChatPromptTemplate.from_template(
    """你是一个严厉的审核员。
    请检查以下报告是否充分回答了用户的问题：{query}
    
    报告内容：
    {report}
    
    请严格按照以下 JSON 格式返回结果（不要包含 Markdown 代码块）：
    {{
        "status": "PASS" 或 "FAIL",
        "feedback": "如果是 PASS，这里留空。如果是 FAIL，请列出 1 个具体的改进建议或需要补充搜索的方向。"
    }}
    """
)

def _clean_json_text(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("```json", "").replace("```", "").strip()
    l = s.find("{")
    r = s.rfind("}")
    if l != -1 and r != -1 and r > l:
        s = s[l:r+1]
    return s

def review_node(state: AgentState):
    query = state["query"]
    report = state["final_report"]
    logger.info(
        "reviewer_started",
        extra={"query_length": len(query), "report_length": len(report)},
    )

    num = state.get("revision_number", 0)

    # Phase 4: 预算执行
    from app.utils.budget_enforcer import create_enforcer_from_state
    enforcer = create_enforcer_from_state(state)

    prompt_text = REVIEW_PROMPT.format(query=query, report=report)
    reviewer_llm = get_llm(model_type="smart")
    response, _ = enforcer.wrap_llm_call("reviewer", reviewer_llm, prompt_text, state)
    raw = response.content
    content = _clean_json_text(raw)

    result = None
    try:
        result = json.loads(content)
    except Exception as e1:
        retry_prompt = f'''
        你刚才的输出无法被 JSON 解析。
        请只输出一行合法 JSON，不要 Markdown，不要解释：
        {{"status":"PASS"或"FAIL","feedback":"PASS留空，FAIL给1条具体建议"}}

        用户问题：{query}
        报告：{report}
        '''
        retry_raw, _ = enforcer.wrap_llm_call(
            "reviewer", reviewer_llm, retry_prompt, state
        )
        retry_raw = retry_raw.content
        retry_content = _clean_json_text(retry_raw)
        try:
            result = json.loads(retry_content)
        except Exception as e2:
            # 兜底策略
            logger.warning(
                "reviewer_json_parse_failed",
                extra={
                    "raw_length": len(raw or ""),
                    "retry_raw_length": len(retry_raw or ""),
                },
            )
            result = {
                "status": "FAIL",
                "feedback": "审查器输出格式异常（未返回合法JSON）。请按要求重写报告，并确保内容充分回答问题且结构清晰；如资料不足请明确说明并提出需要补充检索的点。"
            }

    logger.info(
        "reviewer_completed",
        extra={
            "review_status": result.get("status", "FAIL"),
            "feedback_length": len(result.get("feedback", "")),
            "revision_number": num + 1,
        },
    )
    return {
        "critique": result.get("feedback",""),
        "revision_number": num + 1,
        "review_status": result.get("status", "FAIL")
    }

# 测试函数
# def test_review_node():
#     print("\n========== [TEST] review_node ==========\n")
#
#     # -----------------------------
#     # Case 1: 正常 PASS
#     # -----------------------------
#     state_pass: AgentState = {
#         "query": "解释一下 Beam Search 的 length penalty 如何影响生成结果？",
#         "final_report": "Beam Search 是一种搜索算法，可以找到更好的句子。谢谢。"
#                         "对序列中每个位置，计算它与其它位置的相关性权重，然后对 value 做加权求和，"
#                         "从而在不依赖 RNN 的情况下建模长距离依赖。报告还解释了 Q/K/V 的含义与计算流程。",
#         "revision_number": 0,
#     }
#     out1 = review_node(state_pass)
#     print("[Case 1 Output]", out1)
# test_review_node()

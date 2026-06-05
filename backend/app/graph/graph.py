from langgraph.graph import StateGraph, END
from app.graph.state import AgentState
from app.graph.nodes.planner import plan_node
from app.graph.nodes.researcher import research_node
from app.graph.nodes.writer import write_node
from app.graph.nodes.reviewer import review_node 
import json
from app.graph.nodes.router import route_query
from app.graph.nodes.refiner import refine_node

def route_after_research(state: AgentState):
    """
    Researcher 结束后的交通指挥员。
    检查 state['should_stop'] 是否为 True。
    """

    if state.get("should_stop", False):
        print("--- [路由] 检测到停止信号 (should_stop=True) -> 🛑 提前结束任务 ---")
        return END  
    else:

        return "writer"

def should_continue(state: AgentState):
    """
    决定下一步去哪里的函数。
    返回下一个节点的名称 (字符串) 或 END。
    """
 
    current_revision = state.get("revision_number", 0)
    if current_revision >= 3:
        print("--- [路由] 已达到最大重试次数，强制结束 ---")
        return END

    review_status = state.get("review_status", "PASS")
    critique = state.get("critique", "")
    
    if review_status == "FAIL":
        print(f"--- [路由] 审查未通过 (意见: {critique}) -> 返回规划节点 ---")
        return "planner" 
    else:
        print("--- [路由] 审查通过 -> 结束 ---")
        return END

def create_graph(memory=None):

    workflow = StateGraph(AgentState)

    workflow.add_node("planner", plan_node)
    workflow.add_node("researcher", research_node)
    workflow.add_node("writer", write_node)
    workflow.add_node("reviewer", review_node)
    workflow.add_node("refiner", refine_node)

    # START -> planner -> researcher -> writer -> reviewer -> END/planner
    workflow.set_conditional_entry_point(
        route_query,
        {
            "planner": "planner",
            "refiner": "refiner"
        }
    )
    workflow.add_edge("planner", "researcher")
    workflow.add_conditional_edges(
        "researcher",
        route_after_research,
        {
            "writer": "writer",
            END: END
        }
    )
    workflow.add_edge("writer", "reviewer")

    workflow.add_conditional_edges(
        "reviewer",
        should_continue,
        {
            "planner": "planner",
            END: END
        }
    )
    workflow.add_edge("refiner", END)


    app = workflow.compile(checkpointer=memory)
    return app
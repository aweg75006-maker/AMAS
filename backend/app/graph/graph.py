"""Legacy LangGraph topology retained for rollback and parity checks."""

from langgraph.graph import StateGraph, END
from app.core.logging import get_logger
from app.graph.policies.workflow_loop_policy import WorkflowLoopPolicy
from app.graph.state import AgentState
from app.graph.runtime import wrap_node
from app.harness.registry import get_harness_manifest
from app.graph.nodes.planner import plan_node
from app.graph.nodes.researcher import research_node
from app.graph.nodes.writer import write_node
from app.graph.nodes.reviewer import review_node 
from app.graph.nodes.router import route_query
from app.graph.nodes.refiner import refine_node

logger = get_logger("iris.graph")


def _loop_policy() -> WorkflowLoopPolicy:
    return WorkflowLoopPolicy(max_revisions=get_harness_manifest().max_revisions)

def route_after_research(state: AgentState):
    """
    Researcher 结束后的交通指挥员。
    检查 state['should_stop'] 是否为 True。
    """
    decision = _loop_policy().after_research(state)
    logger.info(decision.reason, extra=decision.metadata)
    return END if decision.next_node == "__end__" else decision.next_node

def should_continue(state: AgentState):
    """
    决定下一步去哪里的函数。
    返回下一个节点的名称 (字符串) 或 END。
    """

    decision = _loop_policy().after_review(state)
    if decision.reason == "review_max_revisions_reached":
        logger.warning(decision.reason, extra=decision.metadata)
    else:
        logger.info(decision.reason, extra=decision.metadata)
    return END if decision.next_node == "__end__" else decision.next_node

def create_graph(memory=None):

    workflow = StateGraph(AgentState)

    workflow.add_node("planner", wrap_node("planner", plan_node))
    workflow.add_node("researcher", wrap_node("researcher", research_node))
    workflow.add_node("writer", wrap_node("writer", write_node))
    workflow.add_node("reviewer", wrap_node("reviewer", review_node))
    workflow.add_node("refiner", wrap_node("refiner", refine_node))

    # START -> planner -> researcher -> writer -> reviewer -> END/planner/writer
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
            "writer": "writer",
            END: END
        }
    )
    workflow.add_edge("refiner", END)


    app = workflow.compile(checkpointer=memory)
    return app

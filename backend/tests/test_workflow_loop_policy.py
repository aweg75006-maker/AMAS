from app.graph.policies.workflow_loop_policy import WorkflowLoopPolicy


def test_loop_policy_routes_research_stop_to_end():
    decision = WorkflowLoopPolicy().after_research({"should_stop": True})

    assert decision.next_node == "__end__"
    assert decision.reason == "research_requested_stop"


def test_loop_policy_routes_research_success_to_writer():
    decision = WorkflowLoopPolicy().after_research({"should_stop": False})

    assert decision.next_node == "writer"
    assert decision.reason == "research_completed"


def test_loop_policy_routes_failed_review_to_planner():
    decision = WorkflowLoopPolicy(max_revisions=3).after_review(
        {
            "revision_number": 1,
            "review_status": "FAIL",
            "critique": "needs more evidence",
            "review_action": "replan",
        }
    )

    assert decision.next_node == "planner"
    assert decision.reason == "review_failed_routing_to_planner"
    assert decision.metadata["critique_length"] == len("needs more evidence")
    assert decision.metadata["review_action"] == "replan"


def test_loop_policy_routes_rewrite_review_to_writer():
    decision = WorkflowLoopPolicy(max_revisions=3).after_review(
        {
            "revision_number": 1,
            "review_status": "FAIL",
            "critique": "结构不清晰，请重写摘要。",
            "review_action": "rewrite",
        }
    )

    assert decision.next_node == "writer"
    assert decision.reason == "review_failed_routing_to_writer"
    assert decision.metadata["review_action"] == "rewrite"


def test_loop_policy_infers_replan_from_critique_when_action_missing():
    decision = WorkflowLoopPolicy(max_revisions=3).after_review(
        {
            "revision_number": 1,
            "review_status": "FAIL",
            "critique": "缺少来源和证据，需要补充检索。",
        }
    )

    assert decision.next_node == "planner"
    assert decision.metadata["review_action"] == "replan"


def test_loop_policy_stops_after_max_revisions():
    decision = WorkflowLoopPolicy(max_revisions=3).after_review(
        {
            "revision_number": 3,
            "review_status": "FAIL",
        }
    )

    assert decision.next_node == "__end__"
    assert decision.reason == "review_max_revisions_reached"


def test_loop_policy_stops_after_passed_review():
    decision = WorkflowLoopPolicy(max_revisions=3).after_review(
        {
            "revision_number": 1,
            "review_status": "PASS",
        }
    )

    assert decision.next_node == "__end__"
    assert decision.reason == "review_passed"

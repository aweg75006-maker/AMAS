import pytest

from app.core.config import settings
from app.core.identity import RequestContext
from app.models.domain import WorkflowRunStatus
from app.repositories.workflow_trace_repository import PostgresWorkflowTraceRepository
from app.services.workflow_trace_service import WorkflowTraceService


@pytest.mark.asyncio
async def test_workflow_trace_service_records_run_node_and_error():
    dsn = settings.secret_value(settings.postgres_dsn)
    assert dsn

    repository = PostgresWorkflowTraceRepository(dsn)
    await repository.connect()
    try:
        service = WorkflowTraceService(repository)
        context = RequestContext(
            tenant_id="tenant_trace",
            user_id="user_trace",
            username="trace",
            role="owner",
            auth_source="jwt",
        )
        run = await service.start_run(
            context=context,
            session_id="iris_trace",
            turn_id="turn_trace",
            knowledge_base_id="kb_trace",
            query="trace query",
            search_mode="hybrid",
            request_id="req_trace",
        )
        await service.record_node_success(
            run=run,
            node_name="writer",
            state_update={"final_report": "trace report"},
            started_at=run.started_at,
            token_usage={"estimated": 1},
        )
        await service.record_tool_run(
            run=run,
            node_name="researcher",
            tool_snapshot={
                "tool_name": "web.search",
                "status": "failed",
                "started_at": run.started_at,
                "finished_at": run.started_at + 0.1,
                "duration_ms": 100,
                "input_summary": "trace query",
                "error_code": "TOOL_FAILED",
                "error_message": "network error",
                "metadata": {"attempts": 2},
            },
        )
        await service.record_route_decision(
            run=run,
            decision_snapshot={
                "from_node": "reviewer",
                "to_node": "writer",
                "reason": "review_failed_routing_to_writer",
                "created_at": run.started_at + 0.2,
                "metadata": {"review_action": "rewrite"},
            },
        )
        await service.finish_run(run, status=WorkflowRunStatus.SUCCEEDED.value)
        await service.record_error_event(
            error_code="TRACE_TEST_ERROR",
            message="trace error",
            context=context,
            request_id="req_trace",
            run_id=run.run_id,
            status_code=500,
        )

        result = await service.get_run_with_nodes(
            tenant_id="tenant_trace",
            run_id=run.run_id,
        )
        errors = await service.list_error_events("tenant_trace", limit=20)

        assert result is not None
        restored_run, nodes, tools, route_decisions = result
        assert restored_run.status == WorkflowRunStatus.SUCCEEDED.value
        assert restored_run.metadata["workflow_version"]
        assert restored_run.metadata["prompt_version"]
        assert nodes[0].node_name == "writer"
        assert nodes[0].metadata["runtime"]["node_policy_version"]
        assert tools[0].tool_name == "web.search"
        assert tools[0].status == "failed"
        assert tools[0].metadata["attempts"] == 2
        assert route_decisions[0].from_node == "reviewer"
        assert route_decisions[0].to_node == "writer"
        assert route_decisions[0].metadata["review_action"] == "rewrite"
        assert any(event.error_code == "TRACE_TEST_ERROR" for event in errors)
    finally:
        await repository.close()

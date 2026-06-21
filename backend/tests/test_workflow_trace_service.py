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
        restored_run, nodes = result
        assert restored_run.status == WorkflowRunStatus.SUCCEEDED.value
        assert restored_run.metadata["workflow_version"]
        assert restored_run.metadata["prompt_version"]
        assert nodes[0].node_name == "writer"
        assert nodes[0].metadata["runtime"]["node_policy_version"]
        assert any(event.error_code == "TRACE_TEST_ERROR" for event in errors)
    finally:
        await repository.close()

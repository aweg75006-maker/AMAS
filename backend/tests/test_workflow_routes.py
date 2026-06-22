import asyncio

from app.core.config import settings
from app.core.identity import RequestContext
from app.core.security import create_access_token
from app.models.domain import TenantRole, WorkflowRunStatus
from app.repositories.workflow_trace_repository import PostgresWorkflowTraceRepository
from app.services.workflow_trace_service import WorkflowTraceService


def _persist_workflow_run():
    dsn = settings.secret_value(settings.postgres_dsn)
    assert dsn

    async def persist():
        repository = PostgresWorkflowTraceRepository(dsn)
        await repository.connect()
        try:
            service = WorkflowTraceService(repository)
            context = RequestContext(
                tenant_id="tenant_workflow_route",
                user_id="user_owner",
                username="owner",
                role=TenantRole.OWNER.value,
                auth_source="jwt",
            )
            run = await service.start_run(
                context=context,
                session_id="iris_route_trace",
                turn_id="turn_route_trace",
                knowledge_base_id="kb_route_trace",
                query="route trace",
                search_mode="hybrid",
                request_id="req_route_trace",
            )
            await service.record_node_success(
                run=run,
                node_name="writer",
                state_update={"final_report": "done"},
                started_at=run.started_at,
            )
            await service.record_tool_run(
                run=run,
                node_name="researcher",
                tool_snapshot={
                    "tool_name": "rag.retrieve",
                    "status": "succeeded",
                    "started_at": run.started_at,
                    "finished_at": run.started_at + 0.1,
                    "duration_ms": 100,
                    "input_summary": "route trace",
                    "output_summary": "doc",
                    "metadata": {"attempts": 1},
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
                error_code="ROUTE_TRACE_ERROR",
                message="route error",
                context=context,
                request_id="req_route_trace",
            )
            return run.run_id
        finally:
            await repository.close()

    return asyncio.run(persist())


def test_owner_can_list_and_get_workflow_run(client):
    run_id = _persist_workflow_run()
    token = create_access_token(
        user_id="user_owner",
        username="owner",
        tenant_id="tenant_workflow_route",
        role=TenantRole.OWNER.value,
        expires_in=60,
    )

    listed = client.get(
        "/api/workflow-runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    detail = client.get(
        f"/api/workflow-runs/{run_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    errors = client.get(
        "/api/error-events",
        headers={"Authorization": f"Bearer {token}"},
    )
    runtime = client.get(
        "/api/workflow-runtime",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert listed.status_code == 200
    assert any(item["run_id"] == run_id for item in listed.json()["items"])
    assert detail.status_code == 200
    assert detail.json()["run"]["run_id"] == run_id
    assert detail.json()["nodes"][0]["node_name"] == "writer"
    assert detail.json()["tools"][0]["tool_name"] == "rag.retrieve"
    assert detail.json()["route_decisions"][0]["to_node"] == "writer"
    assert errors.status_code == 200
    assert any(item["error_code"] == "ROUTE_TRACE_ERROR" for item in errors.json()["items"])
    assert runtime.status_code == 200
    assert runtime.json()["runtime"]["workflow_version"]


def test_viewer_cannot_list_workflow_runs(client):
    token = create_access_token(
        user_id="user_viewer",
        username="viewer",
        tenant_id="tenant_workflow_route",
        role=TenantRole.VIEWER.value,
        expires_in=60,
    )

    response = client.get(
        "/api/workflow-runs",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

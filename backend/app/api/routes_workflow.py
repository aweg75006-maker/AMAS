import time

from fastapi import APIRouter, Depends, Query

from app.api.permissions import WRITE_ROLES, require_roles
from app.api.schemas import CancelWorkflowRunRequest
from app.core.exceptions import AppError
from app.core.identity import RequestContext
from app.models.domain import AuditAction, WorkflowRunRecord, WorkflowRunStatus
from app.services.audit_service import record_audit_event_for_context
from app.services.workflow_runtime_service import workflow_runtime_diagnostics
from app.services.workflow_trace_service import get_workflow_trace_service


router = APIRouter(tags=["workflow"])
require_workflow_reader = require_roles(WRITE_ROLES, allow_header_fallback=False)

TERMINAL_WORKFLOW_STATUSES = {
    WorkflowRunStatus.SUCCEEDED.value,
    WorkflowRunStatus.FAILED.value,
    WorkflowRunStatus.CANCELLED.value,
}


@router.get("/workflow-runtime")
async def get_workflow_runtime_endpoint(
    context: RequestContext = Depends(require_workflow_reader),
):
    return {
        "tenant_id": context.tenant_id,
        "runtime": workflow_runtime_diagnostics(),
    }


@router.get("/workflow-runs")
async def list_workflow_runs_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(require_workflow_reader),
):
    service = await get_workflow_trace_service()
    runs = await service.list_runs(context.tenant_id, limit=limit)
    return {
        "tenant_id": context.tenant_id,
        "items": [_workflow_run_response(run) for run in runs],
    }


@router.get("/workflow-runs/{run_id}")
async def get_workflow_run_endpoint(
    run_id: str,
    context: RequestContext = Depends(require_workflow_reader),
):
    service = await get_workflow_trace_service()
    result = await service.get_run_with_nodes(
        tenant_id=context.tenant_id,
        run_id=run_id,
    )
    if result is None:
        raise AppError(
            code="WORKFLOW_RUN_NOT_FOUND",
            message="工作流执行记录不存在",
            status_code=404,
            details={"run_id": run_id},
        )
    run, nodes, tools, route_decisions = result
    return {
        "run": _workflow_run_response(run),
        "nodes": [node.to_dict() for node in nodes],
        "tools": [tool.to_dict() for tool in tools],
        "route_decisions": [decision.to_dict() for decision in route_decisions],
    }


@router.post("/workflow-runs/{run_id}/cancel")
async def cancel_workflow_run_endpoint(
    run_id: str,
    request: CancelWorkflowRunRequest | None = None,
    context: RequestContext = Depends(require_workflow_reader),
):
    service = await get_workflow_trace_service()
    existing = await service.repository.get_workflow_run(run_id)
    if existing is None or existing.tenant_id != context.tenant_id:
        raise AppError(
            code="WORKFLOW_RUN_NOT_FOUND",
            message="工作流执行记录不存在",
            status_code=404,
            details={"run_id": run_id},
        )
    if existing.status != WorkflowRunStatus.RUNNING.value:
        raise AppError(
            code="WORKFLOW_RUN_NOT_RUNNING",
            message="只有运行中的工作流可以取消",
            status_code=409,
            details={"run_id": run_id, "status": existing.status},
        )

    reason = (request.reason if request else "") or "cancelled by user"
    run = await service.cancel_run(
        tenant_id=context.tenant_id,
        run_id=run_id,
        cancelled_by=context.user_id,
        reason=reason,
    )
    if run is None:
        raise AppError(
            code="WORKFLOW_RUN_NOT_FOUND",
            message="工作流执行记录不存在",
            status_code=404,
            details={"run_id": run_id},
        )
    if run.status != WorkflowRunStatus.CANCELLED.value:
        raise AppError(
            code="WORKFLOW_RUN_NOT_RUNNING",
            message="只有运行中的工作流可以取消",
            status_code=409,
            details={"run_id": run_id, "status": run.status},
        )
    await service.record_error_event(
        error_code="WORKFLOW_RUN_CANCELLED",
        message="工作流已取消",
        source="workflow",
        severity="warning",
        context=context,
        request_id=run.request_id,
        session_id=run.session_id,
        turn_id=run.turn_id,
        run_id=run.run_id,
        status_code=409,
        details={"reason": reason, "cancelled_by": context.user_id},
    )
    await record_audit_event_for_context(
        context,
        action=AuditAction.WORKFLOW_RUN_CANCELLED.value,
        target_type="workflow_run",
        target_id=run.run_id,
        details={"reason": reason, "status": run.status},
    )
    return {"run": _workflow_run_response(run)}


@router.get("/error-events")
async def list_error_events_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(require_workflow_reader),
):
    service = await get_workflow_trace_service()
    events = await service.list_error_events(context.tenant_id, limit=limit)
    return {
        "tenant_id": context.tenant_id,
        "items": [event.to_dict() for event in events],
    }


def _workflow_run_response(run: WorkflowRunRecord) -> dict:
    payload = run.to_dict()
    is_terminal = run.status in TERMINAL_WORKFLOW_STATUSES
    finished_at = run.finished_at or time.time()
    running_duration_ms = run.duration_ms
    if not is_terminal:
        running_duration_ms = int((finished_at - run.started_at) * 1000)
    payload.update(
        {
            "running_duration_ms": max(0, running_duration_ms),
            "is_terminal": is_terminal,
            "can_cancel": run.status == WorkflowRunStatus.RUNNING.value,
        }
    )
    return payload

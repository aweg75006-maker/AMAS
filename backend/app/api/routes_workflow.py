from fastapi import APIRouter, Depends, Query

from app.api.permissions import WRITE_ROLES, require_roles
from app.core.exceptions import AppError
from app.core.identity import RequestContext
from app.services.workflow_trace_service import get_workflow_trace_service


router = APIRouter(tags=["workflow"])
require_workflow_reader = require_roles(WRITE_ROLES, allow_header_fallback=False)


@router.get("/workflow-runs")
async def list_workflow_runs_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(require_workflow_reader),
):
    service = await get_workflow_trace_service()
    runs = await service.list_runs(context.tenant_id, limit=limit)
    return {
        "tenant_id": context.tenant_id,
        "items": [run.to_dict() for run in runs],
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
    run, nodes = result
    return {
        "run": run.to_dict(),
        "nodes": [node.to_dict() for node in nodes],
    }


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

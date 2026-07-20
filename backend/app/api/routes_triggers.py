"""
被动触发 API：Webhook 接收 + 定时任务（Cron）管理。

- POST /api/triggers/webhook          外部系统携带令牌触发一次研究（后台执行 + 飞书通知）
- GET  /api/triggers/cron/jobs        列出定时任务
- POST /api/triggers/cron/jobs        创建定时任务
- GET  /api/triggers/cron/jobs/{id}   查询单个定时任务
- PATCH/PUT /api/triggers/cron/jobs/{id}  更新定时任务
- DELETE /api/triggers/cron/jobs/{id} 删除定时任务
- POST /api/triggers/cron/jobs/{id}/run  立即执行一次（用于调试）
"""
from __future__ import annotations

import hmac
import time
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from app.api.permissions import require_read_access
from app.api.schemas import CronJobCreateRequest, CronJobUpdateRequest, TriggerWebhookRequest
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.identity import (
    DEFAULT_TENANT_ID,
    DEFAULT_USER_ID,
    RequestContext,
    clean_context_id,
)
from app.core.logging import get_logger
from app.services.trigger_scheduler import (
    CronJob,
    TriggerScheduler,
    compute_next_run_at,
    get_trigger_scheduler,
)
from app.services.trigger_service import run_research_and_notify


router = APIRouter(tags=["triggers"])
logger = get_logger("iris.api.triggers")


def _require_webhook_token(token: Optional[str]) -> None:
    expected = settings.webhook_trigger_token
    if not expected:
        raise AppError(
            code="WEBHOOK_TRIGGER_DISABLED",
            message="Webhook 被动触发未启用，请在 backend/.env 配置 WEBHOOK_TRIGGER_TOKEN",
            status_code=503,
        )
    if not token or not hmac.compare_digest(token, expected):
        raise AppError(
            code="WEBHOOK_TRIGGER_UNAUTHORIZED",
            message="Webhook 触发令牌无效",
            status_code=401,
        )


@router.post("/triggers/webhook")
async def trigger_webhook(
    request: TriggerWebhookRequest,
    background_tasks: BackgroundTasks,
):
    """外部系统触发研究任务。

    校验令牌后，研究在后台执行，结果（若 notify=true）通过飞书推送。
    接口立即返回 accepted，可通过 /api/workflow-runs 轮询状态。
    """
    _require_webhook_token(request.token)
    context = RequestContext(
        tenant_id=clean_context_id(request.tenant_id, DEFAULT_TENANT_ID),
        user_id=clean_context_id(request.user_id, DEFAULT_USER_ID),
        auth_source="webhook",
    )
    trigger_id = uuid4().hex
    background_tasks.add_task(
        _run_trigger_job,
        trigger_id=trigger_id,
        query=request.query,
        context=context,
        search_mode=request.search_mode,
        knowledge_base_id=request.knowledge_base_id,
        session_id=request.session_id,
        notify=request.notify,
        notify_webhook_url=request.notify_webhook_url,
    )
    return {
        "status": "accepted",
        "trigger_id": trigger_id,
        "notify": request.notify,
        "poll": "/api/workflow-runs",
        "note": "研究任务已在后台启动；若 notify=true，结果将通过飞书推送。",
    }


@router.get("/triggers/cron/jobs")
async def list_cron_jobs(
    context: RequestContext = Depends(require_read_access),
):
    scheduler = get_trigger_scheduler()
    items = [job.to_dict() for job in scheduler.list_jobs()]
    return {"items": items, "count": len(items)}


@router.post("/triggers/cron/jobs")
async def create_cron_job(
    request: CronJobCreateRequest,
    context: RequestContext = Depends(require_read_access),
):
    scheduler = get_trigger_scheduler()
    if request.job_id and scheduler.get_job(request.job_id):
        raise AppError(
            code="CRON_JOB_EXISTS",
            message="该 job_id 已存在",
            status_code=409,
            details={"job_id": request.job_id},
        )
    # 调度配置合法性校验（无法解析则拒绝）。
    if compute_next_run_at(request.schedule, time.time()) is None:
        raise AppError(
            code="CRON_SCHEDULE_INVALID",
            message="无法解析调度配置",
            status_code=400,
            details={"schedule": request.schedule},
        )

    job_id = request.job_id or f"job_{uuid4().hex[:12]}"
    job = CronJob(
        job_id=job_id,
        query=request.query,
        schedule=request.schedule,
        search_mode=request.search_mode,
        knowledge_base_id=request.knowledge_base_id,
        session_id=request.session_id,
        notify=request.notify,
        enabled=request.enabled,
        tenant_id=request.tenant_id or context.tenant_id,
        user_id=request.user_id or context.user_id,
    )
    job.next_run_at = compute_next_run_at(request.schedule, time.time())
    await scheduler.save_job(job)
    return {"job": job.to_dict()}


@router.get("/triggers/cron/jobs/{job_id}")
async def get_cron_job(
    job_id: str,
    context: RequestContext = Depends(require_read_access),
):
    scheduler = get_trigger_scheduler()
    job = scheduler.get_job(job_id)
    if job is None:
        raise AppError(
            code="CRON_JOB_NOT_FOUND",
            message="定时任务不存在",
            status_code=404,
            details={"job_id": job_id},
        )
    return {"job": job.to_dict()}


@router.patch("/triggers/cron/jobs/{job_id}")
async def update_cron_job(
    job_id: str,
    request: CronJobUpdateRequest,
    context: RequestContext = Depends(require_read_access),
):
    scheduler = get_trigger_scheduler()
    job = scheduler.get_job(job_id)
    if job is None:
        raise AppError(
            code="CRON_JOB_NOT_FOUND",
            message="定时任务不存在",
            status_code=404,
            details={"job_id": job_id},
        )
    updates = request.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key == "schedule":
            job.schedule = value
            job.next_run_at = compute_next_run_at(value, time.time())  # 重新计算下次执行时间
        elif hasattr(job, key):
            setattr(job, key, value)
    await scheduler.save_job(job)
    return {"job": job.to_dict()}


@router.delete("/triggers/cron/jobs/{job_id}")
async def delete_cron_job(
    job_id: str,
    context: RequestContext = Depends(require_read_access),
):
    scheduler = get_trigger_scheduler()
    if scheduler.get_job(job_id) is None:
        raise AppError(
            code="CRON_JOB_NOT_FOUND",
            message="定时任务不存在",
            status_code=404,
            details={"job_id": job_id},
        )
    await scheduler.remove_job(job_id)
    return {"deleted": job_id}


@router.post("/triggers/cron/jobs/{job_id}/run")
async def run_cron_job_now(
    job_id: str,
    background_tasks: BackgroundTasks,
    context: RequestContext = Depends(require_read_access),
):
    """立即执行一次定时任务（绕过调度，用于调试）。"""
    scheduler = get_trigger_scheduler()
    job = scheduler.get_job(job_id)
    if job is None:
        raise AppError(
            code="CRON_JOB_NOT_FOUND",
            message="定时任务不存在",
            status_code=404,
            details={"job_id": job_id},
        )
    trigger_id = f"manual-{job_id}-{uuid4().hex[:8]}"
    run_context = RequestContext(
        tenant_id=job.tenant_id or DEFAULT_TENANT_ID,
        user_id=job.user_id or DEFAULT_USER_ID,
        auth_source="manual",
    )
    background_tasks.add_task(
        _run_trigger_job,
        trigger_id=trigger_id,
        query=job.query,
        context=run_context,
        search_mode=job.search_mode,
        knowledge_base_id=job.knowledge_base_id,
        session_id=job.session_id,
        notify=job.notify,
        notify_webhook_url=None,
    )
    return {"status": "accepted", "trigger_id": trigger_id}


async def _run_trigger_job(
    *,
    trigger_id: str,
    query: str,
    context: RequestContext,
    search_mode: str,
    knowledge_base_id: Optional[str],
    session_id: Optional[str],
    notify: bool,
    notify_webhook_url: Optional[str],
) -> None:
    """后台执行研究任务（被 Webhook / 手动执行复用）。异常仅记日志。"""
    try:
        await run_research_and_notify(
            query=query,
            context=context,
            search_mode=search_mode,
            knowledge_base_id=knowledge_base_id,
            session_id=session_id,
            notify=notify,
            notify_webhook_url=notify_webhook_url,
            request_id=trigger_id,
        )
    except Exception as exc:
        logger.exception(
            "trigger_job_failed",
            extra={"trigger_id": trigger_id, "error": str(exc)},
        )

"""
触发调度器（Cron）。

- 在内存中维护定时研究任务（CronJob），并持久化到 Redis（key: trigger:cron_job:{id}），
  Redis 不可用时降级为内存存储（重启即丢失）。
- 启动时从 Redis 载入任务；若为空且配置了 ``settings.cron_jobs``（环境变量 CRON_JOBS），
  则写入预置任务。
- 后台循环按 ``cron_poll_interval_seconds`` 轮询，到期任务通过
  ``run_research_and_notify`` 异步执行（并完成飞书通知）。

调度类型（schedule.type）：
- interval: {"type":"interval","seconds":3600}        每 N 秒
- daily:    {"type":"daily","hour":9,"minute":0}       每天本地时区 H:M
- cron:     {"type":"cron","expr":"0 9 * * *"}         标准 5 段 crontab
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.config import settings
from app.core.identity import DEFAULT_TENANT_ID, DEFAULT_USER_ID, RequestContext
from app.core.logging import get_logger
from app.utils.redis_client import get_redis


logger = get_logger("iris.trigger.scheduler")

JOB_KEY_PREFIX = "trigger:cron_job:"
CRON_JOB_TTL_SECONDS = 60 * 60 * 24 * 30


@dataclass
class CronJob:
    """一条定时研究任务的定义与运行时状态。"""

    job_id: str
    query: str
    schedule: dict[str, Any]
    search_mode: str = "hybrid"
    knowledge_base_id: Optional[str] = None
    session_id: Optional[str] = None
    notify: bool = True
    enabled: bool = True
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    # 运行时字段（持久化以便观测）
    last_run_at: Optional[float] = None
    last_status: Optional[str] = None
    next_run_at: Optional[float] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CronJob":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


# ─── 调度时间计算 ───


def compute_next_run_at(schedule: dict[str, Any], after: float) -> Optional[float]:
    """根据调度配置计算下一次执行时间戳（UTC 秒）。无法解析返回 None。"""
    stype = schedule.get("type", "interval")
    if stype == "interval":
        seconds = float(schedule.get("seconds", 3600))
        if seconds <= 0:
            return None
        return after + seconds
    if stype == "daily":
        return _next_daily(schedule, after)
    if stype == "cron":
        return _next_cron(schedule.get("expr", ""), after)
    logger.warning("cron_schedule_unknown_type", extra={"type": stype})
    return None


def _next_daily(schedule: dict[str, Any], after: float) -> float:
    hour = int(schedule.get("hour", 9))
    minute = int(schedule.get("minute", 0))
    dt = datetime.fromtimestamp(after)
    candidate = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate.timestamp() <= after:
        candidate += timedelta(days=1)
    return candidate.timestamp()


def _cron_field(field: str, min_val: int, max_val: int) -> set[int]:
    """解析单个 crontab 字段为允许的取值集合。支持 *、a-b、a,b、*/n、a-b/n。"""
    result: set[int] = set()
    field = field.strip()
    if field in ("", "*"):
        return set(range(min_val, max_val + 1))
    for part in field.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            range_part, step_part = part.split("/", 1)
            step = int(step_part)
        else:
            range_part = part
        if range_part in ("", "*"):
            lo, hi = min_val, max_val
        elif "-" in range_part:
            lo, hi = (int(x) for x in range_part.split("-", 1))
        else:
            lo = hi = int(range_part)
        for v in range(lo, hi + 1, step):
            if min_val <= v <= max_val:
                result.add(v)
    return result


def _next_cron(expr: str, after: float, limit_years: int = 2) -> Optional[float]:
    fields = expr.split()
    if len(fields) != 5:
        logger.warning("cron_expr_invalid", extra={"expr": expr})
        return None
    minute_set = _cron_field(fields[0], 0, 59)
    hour_set = _cron_field(fields[1], 0, 23)
    dom_set = _cron_field(fields[2], 1, 31)
    month_set = _cron_field(fields[3], 1, 12)
    dow_set = _cron_field(fields[4], 0, 6)  # 0=周日 .. 6=周六
    # 把 cron 的 dow(0=周日) 映射到 Python weekday()(0=周一..6=周日)
    mapped_dow = {(d - 1) % 7 for d in dow_set}

    dom_restricted = fields[2].strip() != "*"
    dow_restricted = fields[4].strip() != "*"

    dt = datetime.fromtimestamp(after).replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = dt + timedelta(days=365 * limit_years)
    while dt <= end:
        if (
            dt.minute in minute_set
            and dt.hour in hour_set
            and dt.month in month_set
        ):
            day_matches_dom = dt.day in dom_set
            day_matches_dow = dt.weekday() in mapped_dow
            if dom_restricted and dow_restricted:
                day_ok = day_matches_dom or day_matches_dow
            else:
                day_ok = day_matches_dom and day_matches_dow
            if day_ok:
                return dt.timestamp()
        dt += timedelta(minutes=1)
    logger.warning("cron_expr_no_match_within_limit", extra={"expr": expr})
    return None


# ─── 调度器 ───


class TriggerScheduler:
    """进程内调度器单例：管理 CronJob 生命周期并驱动后台执行循环。"""

    def __init__(self) -> None:
        self._jobs: dict[str, CronJob] = {}
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def load_jobs(self) -> None:
        redis = await get_redis()
        keys = await redis.keys(f"{JOB_KEY_PREFIX}*")
        for key in keys:
            raw = await redis.get(key)
            if not raw:
                continue
            try:
                self._jobs[CronJob.from_dict(json.loads(raw)).job_id] = CronJob.from_dict(
                    json.loads(raw)
                )
            except Exception as exc:
                logger.warning("cron_job_load_failed", extra={"error": str(exc)})
        # 若存储为空且配置了预置任务，则写入。
        if not self._jobs and settings.cron_jobs:
            for spec in settings.cron_jobs:
                try:
                    job = CronJob.from_dict(spec)
                    await self.save_job(job)
                except Exception as exc:
                    logger.warning(
                        "cron_seed_job_failed", extra={"error": str(exc), "spec": spec}
                    )

    async def save_job(self, job: CronJob) -> None:
        self._jobs[job.job_id] = job
        try:
            redis = await get_redis()
            await redis.set(
                f"{JOB_KEY_PREFIX}{job.job_id}",
                json.dumps(job.to_dict()),
                ex=CRON_JOB_TTL_SECONDS,
            )
        except Exception as exc:  # 持久化失败仅记日志，内存态仍可用
            logger.warning("cron_job_save_failed", extra={"error": str(exc)})

    async def remove_job(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        try:
            redis = await get_redis()
            await redis.delete(f"{JOB_KEY_PREFIX}{job_id}")
        except Exception as exc:
            logger.warning("cron_job_delete_failed", extra={"error": str(exc)})

    def list_jobs(self) -> list[CronJob]:
        return list(self._jobs.values())

    def get_job(self, job_id: str) -> Optional[CronJob]:
        return self._jobs.get(job_id)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self.load_jobs()
        self._task = asyncio.create_task(self._loop())
        logger.info("cron_scheduler_started", extra={"jobs": len(self._jobs)})

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("cron_scheduler_stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception as exc:  # 单轮异常不应终止调度循环
                logger.exception("cron_tick_error", extra={"error": str(exc)})
            await asyncio.sleep(max(1.0, settings.cron_poll_interval_seconds))

    async def _tick(self) -> None:
        now = time.time()
        for job in list(self._jobs.values()):
            if not job.enabled:
                continue
            if job.next_run_at is None:
                job.next_run_at = compute_next_run_at(job.schedule, now)
                await self.save_job(job)
                continue
            if job.next_run_at <= now:
                await self._dispatch(job, now)

    async def _dispatch(self, job: CronJob, now: float) -> None:
        from app.services.trigger_service import run_research_and_notify

        context = RequestContext(
            tenant_id=job.tenant_id or DEFAULT_TENANT_ID,
            user_id=job.user_id or DEFAULT_USER_ID,
            auth_source="cron",
        )
        job.last_run_at = now
        job.next_run_at = compute_next_run_at(job.schedule, now)
        await self.save_job(job)

        from uuid import uuid4

        trigger_id = f"cron-{job.job_id}-{uuid4().hex[:8]}"
        asyncio.create_task(self._safe_run(trigger_id, job, context))

    async def _safe_run(self, trigger_id: str, job: CronJob, context: RequestContext) -> None:
        from app.services.trigger_service import run_research_and_notify

        try:
            result = await run_research_and_notify(
                query=job.query,
                context=context,
                search_mode=job.search_mode,
                knowledge_base_id=job.knowledge_base_id,
                session_id=job.session_id,
                notify=job.notify,
                request_id=trigger_id,
            )
            job.last_status = result.get("status")
            await self.save_job(job)
        except Exception as exc:
            job.last_status = "failed"
            await self.save_job(job)
            logger.exception(
                "cron_job_run_failed",
                extra={"job_id": job.job_id, "trigger_id": trigger_id, "error": str(exc)},
            )


_scheduler: Optional[TriggerScheduler] = None


def get_trigger_scheduler() -> TriggerScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = TriggerScheduler()
    return _scheduler

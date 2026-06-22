from __future__ import annotations

import time
from uuid import uuid4

from app.core.identity import RequestContext
from app.core.logging import get_logger, get_request_id
from app.models.domain import (
    ErrorEventRecord,
    WorkflowNodeRunRecord,
    WorkflowNodeStatus,
    WorkflowRouteDecisionRecord,
    WorkflowRunRecord,
    WorkflowRunStatus,
    WorkflowToolRunRecord,
)
from app.repositories.workflow_trace_repository import (
    WorkflowTraceRepository,
    get_workflow_trace_repository,
)
from app.services.workflow_runtime_service import workflow_runtime_fingerprint


logger = get_logger("iris.workflow_trace")


class WorkflowTraceService:
    """Records durable workflow runs, node runs, and error events."""

    def __init__(self, repository: WorkflowTraceRepository):
        self.repository = repository

    async def start_run(
        self,
        *,
        context: RequestContext,
        session_id: str,
        turn_id: str,
        knowledge_base_id: str,
        query: str,
        search_mode: str,
        request_id: str = "",
        metadata: dict | None = None,
    ) -> WorkflowRunRecord:
        run = WorkflowRunRecord(
            run_id=f"run_{uuid4().hex[:16]}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            username=context.username,
            session_id=session_id,
            turn_id=turn_id,
            knowledge_base_id=knowledge_base_id,
            request_id=request_id or get_request_id(),
            query=query,
            search_mode=search_mode,
            status=WorkflowRunStatus.RUNNING.value,
            metadata={**workflow_runtime_fingerprint(), **(metadata or {})},
        )
        await self.repository.save_workflow_run(run)
        return run

    async def finish_run(
        self,
        run: WorkflowRunRecord,
        *,
        status: str = WorkflowRunStatus.SUCCEEDED.value,
        error_code: str = "",
        error_message: str = "",
        metadata: dict | None = None,
    ) -> WorkflowRunRecord:
        now = time.time()
        run.status = status
        run.finished_at = now
        run.duration_ms = int((now - run.started_at) * 1000)
        run.error_code = error_code
        run.error_message = error_message[:1000]
        if metadata:
            run.metadata = {**run.metadata, **metadata}
        await self.repository.save_workflow_run(run)
        return run

    async def record_node_success(
        self,
        *,
        run: WorkflowRunRecord,
        node_name: str,
        state_update: dict,
        started_at: float,
        token_usage: dict | None = None,
    ) -> WorkflowNodeRunRecord:
        finished_at = time.time()
        node_run = WorkflowNodeRunRecord(
            node_run_id=f"node_{uuid4().hex[:16]}",
            run_id=run.run_id,
            node_name=node_name,
            tenant_id=run.tenant_id,
            session_id=run.session_id,
            turn_id=run.turn_id,
            status=WorkflowNodeStatus.SUCCEEDED.value,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=int((finished_at - started_at) * 1000),
            input_summary=self._summarize_text(run.query),
            output_summary=self._summarize_state_update(state_update),
            token_usage=token_usage or {},
            metadata={
                "state_keys": sorted(state_update.keys()),
                "workflow_event": state_update.get("_workflow_event", {}),
                "runtime": workflow_runtime_fingerprint(),
            },
        )
        await self.repository.save_node_run(node_run)
        return node_run

    async def record_node_failure(
        self,
        *,
        run: WorkflowRunRecord,
        node_name: str,
        error_code: str,
        error_message: str,
        duration_ms: int = 0,
        attempts: int = 1,
    ) -> WorkflowNodeRunRecord:
        now = time.time()
        started_at = now - max(duration_ms, 0) / 1000
        node_run = WorkflowNodeRunRecord(
            node_run_id=f"node_{uuid4().hex[:16]}",
            run_id=run.run_id,
            node_name=node_name,
            tenant_id=run.tenant_id,
            session_id=run.session_id,
            turn_id=run.turn_id,
            status=WorkflowNodeStatus.FAILED.value,
            started_at=started_at,
            finished_at=now,
            duration_ms=duration_ms,
            input_summary=self._summarize_text(run.query),
            output_summary="",
            error_code=error_code,
            error_message=error_message[:1000],
            metadata={
                "attempts": attempts,
                "runtime": workflow_runtime_fingerprint(),
            },
        )
        await self.repository.save_node_run(node_run)
        return node_run

    async def record_tool_run(
        self,
        *,
        run: WorkflowRunRecord,
        node_name: str,
        tool_snapshot: dict,
    ) -> WorkflowToolRunRecord:
        tool_run = WorkflowToolRunRecord(
            tool_run_id=tool_snapshot.get("tool_run_id") or f"tool_{uuid4().hex[:16]}",
            run_id=run.run_id,
            node_name=node_name,
            tool_name=tool_snapshot.get("tool_name", ""),
            tenant_id=run.tenant_id,
            session_id=run.session_id,
            turn_id=run.turn_id,
            status=tool_snapshot.get("status", "succeeded"),
            started_at=float(tool_snapshot.get("started_at", time.time()) or time.time()),
            finished_at=float(tool_snapshot.get("finished_at", time.time()) or time.time()),
            duration_ms=int(tool_snapshot.get("duration_ms", 0) or 0),
            input_summary=self._summarize_text(tool_snapshot.get("input_summary", "")),
            output_summary=self._summarize_text(tool_snapshot.get("output_summary", "")),
            error_code=tool_snapshot.get("error_code", ""),
            error_message=self._summarize_text(tool_snapshot.get("error_message", ""), 1000),
            metadata={
                **(tool_snapshot.get("metadata") or {}),
                "runtime": workflow_runtime_fingerprint(),
            },
        )
        await self.repository.save_tool_run(tool_run)
        return tool_run

    async def record_route_decision(
        self,
        *,
        run: WorkflowRunRecord,
        decision_snapshot: dict,
    ) -> WorkflowRouteDecisionRecord:
        decision = WorkflowRouteDecisionRecord(
            decision_id=decision_snapshot.get("decision_id") or f"route_{uuid4().hex[:16]}",
            run_id=run.run_id,
            from_node=decision_snapshot.get("from_node", ""),
            to_node=decision_snapshot.get("to_node", ""),
            reason=decision_snapshot.get("reason", ""),
            tenant_id=run.tenant_id,
            session_id=run.session_id,
            turn_id=run.turn_id,
            created_at=float(decision_snapshot.get("created_at", time.time()) or time.time()),
            metadata={
                **(decision_snapshot.get("metadata") or {}),
                "runtime": workflow_runtime_fingerprint(),
            },
        )
        await self.repository.save_route_decision(decision)
        return decision

    async def record_error_event(
        self,
        *,
        error_code: str,
        message: str,
        source: str = "api",
        severity: str = "error",
        context: RequestContext | None = None,
        request_id: str = "",
        session_id: str = "",
        turn_id: str = "",
        run_id: str = "",
        node_name: str = "",
        path: str = "",
        status_code: int = 500,
        details: dict | None = None,
    ) -> ErrorEventRecord:
        event = ErrorEventRecord(
            error_event_id=f"err_{uuid4().hex[:16]}",
            error_code=error_code,
            message=message[:1000],
            source=source,
            severity=severity,
            tenant_id=context.tenant_id if context else "",
            user_id=context.user_id if context else "",
            username=context.username if context else "",
            request_id=request_id or get_request_id(),
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            node_name=node_name,
            path=path,
            status_code=status_code,
            details=details or {},
        )
        await self.repository.save_error_event(event)
        return event

    async def list_runs(self, tenant_id: str, *, limit: int = 50) -> list[WorkflowRunRecord]:
        return await self.repository.list_workflow_runs(
            tenant_id,
            limit=max(1, min(limit, 200)),
        )

    async def get_run_with_nodes(
        self,
        *,
        tenant_id: str,
        run_id: str,
    ) -> tuple[
        WorkflowRunRecord,
        list[WorkflowNodeRunRecord],
        list[WorkflowToolRunRecord],
        list[WorkflowRouteDecisionRecord],
    ] | None:
        run = await self.repository.get_workflow_run(run_id)
        if run is None or run.tenant_id != tenant_id:
            return None
        nodes = await self.repository.list_node_runs(run_id)
        tools = await self.repository.list_tool_runs(run_id)
        route_decisions = await self.repository.list_route_decisions(run_id)
        return run, nodes, tools, route_decisions

    async def list_error_events(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
    ) -> list[ErrorEventRecord]:
        return await self.repository.list_error_events(
            tenant_id,
            limit=max(1, min(limit, 200)),
        )

    def _summarize_text(self, value: str, max_len: int = 500) -> str:
        text = " ".join(str(value or "").split())
        return text[:max_len]

    def _summarize_state_update(self, state_update: dict, max_len: int = 1000) -> str:
        for key in ("final_report", "critique", "plan", "search_results"):
            value = state_update.get(key)
            if not value:
                continue
            if isinstance(value, list):
                return self._summarize_text(" ".join(str(item) for item in value), max_len)
            return self._summarize_text(str(value), max_len)
        return self._summarize_text(str(sorted(state_update.keys())), max_len)


async def get_workflow_trace_service() -> WorkflowTraceService:
    repository = await get_workflow_trace_repository()
    return WorkflowTraceService(repository)


async def safe_record_error_event(**kwargs) -> ErrorEventRecord | None:
    try:
        service = await get_workflow_trace_service()
        return await service.record_error_event(**kwargs)
    except Exception:
        logger.exception("error_event_write_failed", extra={"error_code": kwargs.get("error_code")})
        return None

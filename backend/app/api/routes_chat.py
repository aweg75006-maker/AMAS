import asyncio
import json
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.context import RequestContext, get_request_context
from app.api.dependencies import get_assembler
from app.api.rate_limits import chat_rate_limit
from app.api.schemas import ChatRequest, ResumeChatRequest
from app.core.config import settings
from app.core.errors import sse_error_event
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.graph.engine import WorkflowEngineExecutionError, WorkflowPausedError
from app.graph.engine_factory import create_workflow_engine
from app.graph.runtime import WorkflowNodeExecutionError
from app.models.domain import WorkflowRunStatus
from app.services.chat_history_service import persist_completed_chat_turn
from app.services.knowledge_base_service import get_knowledge_base_service
from app.services.workflow_trace_service import get_workflow_trace_service
from app.utils.budget_ledger import BudgetLedger
from app.utils.context_assembler import ContextAssembler
from app.utils.redis_client import get_redis


router = APIRouter()
logger = get_logger("iris.api.chat")


@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    http_request: Request,
    _rate_limit: None = Depends(chat_rate_limit),
    context: RequestContext = Depends(get_request_context),
):
    """
    Multi-turn research chat endpoint.

    The endpoint streams workflow node updates with SSE.
    """
    kb_service = await get_knowledge_base_service()
    knowledge_base_id = (
        request.knowledge_base_id
        or kb_service.default_knowledge_base_id(context.tenant_id)
    )
    kb = await kb_service.get_knowledge_base_for_tenant(
        knowledge_base_id,
        context.tenant_id,
    )
    if kb is None and knowledge_base_id == kb_service.default_knowledge_base_id(context.tenant_id):
        kb = await kb_service.ensure_default_knowledge_base(
            tenant_id=context.tenant_id,
            created_by=context.user_id,
        )
    if kb is None:
        raise AppError(
            code="KNOWLEDGE_BASE_NOT_FOUND",
            message="知识库不存在",
            status_code=404,
            details={"knowledge_base_id": knowledge_base_id},
        )

    assembler = await get_assembler()
    initial_state, ledger, memory = await assembler.prepare(
        query=request.query,
        search_mode=request.search_mode,
        session_id=request.session_id,
        pinned_turn_ids=request.pinned_turn_ids,
    )
    initial_state["knowledge_base_id"] = knowledge_base_id
    initial_state["tenant_id"] = context.tenant_id

    session_id = initial_state["session_id"]
    turn_id = initial_state["turn_id"]
    request_id = getattr(http_request.state, "request_id", "-")

    config = {
        "configurable": {
            "thread_id": request.thread_id or turn_id,
            "session_id": session_id,
            "hitl_pause_before": request.hitl_pause_before,
        }
    }

    return StreamingResponse(
        _chat_event_stream(
            initial_state=initial_state,
            config=config,
            assembler=assembler,
            ledger=ledger,
            memory=memory,
            context=context,
            http_request=http_request,
            knowledge_base_id=knowledge_base_id,
            query=request.query,
            search_mode=request.search_mode,
            session_id=session_id,
            turn_id=turn_id,
        ),
        media_type="text/event-stream",
    )


@router.post("/chat/resume")
async def chat_resume_endpoint(
    request: ResumeChatRequest,
    http_request: Request,
    _rate_limit: None = Depends(chat_rate_limit),
    context: RequestContext = Depends(get_request_context),
):
    """
    断点续跑：依据 thread_id 加载最近一次 checkpoint，从断点恢复工作流执行。

    适用于运行被取消/崩溃后，从最后一个已完成节点之后继续，
    无需重跑已完成节点（其产物已合并进 checkpoint 状态）。
    """
    redis = await get_redis()
    raw = await redis.get_checkpoint(request.thread_id, "main")
    if not raw:
        raise AppError(
            code="WORKFLOW_CHECKPOINT_NOT_FOUND",
            message="未找到可恢复的断点，请确认 thread_id 是否正确，或任务是否已正常结束",
            status_code=404,
            details={"thread_id": request.thread_id},
        )
    checkpoint = json.loads(raw)
    state = dict(checkpoint.get("state", {}))
    session_id = state.get("session_id", "")
    turn_id = state.get("turn_id", "")
    query = state.get("query", "")
    search_mode = state.get("search_mode", "hybrid")
    if not session_id:
        raise AppError(
            code="WORKFLOW_CHECKPOINT_INVALID",
            message="断点数据缺少会话信息，无法恢复",
            status_code=409,
            details={"thread_id": request.thread_id},
        )

    kb_service = await get_knowledge_base_service()
    knowledge_base_id = state.get("knowledge_base_id") or kb_service.default_knowledge_base_id(
        context.tenant_id
    )
    kb = await kb_service.get_knowledge_base_for_tenant(knowledge_base_id, context.tenant_id)
    if kb is None and knowledge_base_id == kb_service.default_knowledge_base_id(context.tenant_id):
        kb = await kb_service.ensure_default_knowledge_base(
            tenant_id=context.tenant_id,
            created_by=context.user_id,
        )
    if kb is None:
        raise AppError(
            code="KNOWLEDGE_BASE_NOT_FOUND",
            message="知识库不存在",
            status_code=404,
            details={"knowledge_base_id": knowledge_base_id},
        )

    # 重建装配器与预算账簿（从断点预算快照恢复会话累计 Token）。
    assembler = ContextAssembler()
    await assembler._init()
    ledger = BudgetLedger(session_id=session_id, total_budget=settings.total_token_budget)
    ledger.begin_turn(state.get("turn_number", 1), turn_id)
    budget_state = state.get("budget_state") or {}
    ledger._session_estimated = int(budget_state.get("session_estimated_total", 0) or 0)
    ledger._session_actual = int(budget_state.get("session_actual_total", 0) or 0)
    ledger._compression_savings = int(budget_state.get("compression_savings", 0) or 0)

    # 可选：续跑时追加人工补充指令 / 注入 HITL 人工输入。
    if request.resume_instruction:
        state["query"] = f"{query}\n\n[续跑补充指令] {request.resume_instruction}"
        query = state["query"]
    if request.human_input:
        state["human_input"] = request.human_input

    config = {
        "configurable": {
            "thread_id": request.thread_id,
            "session_id": session_id,
        }
    }

    return StreamingResponse(
        _chat_event_stream(
            initial_state=state,
            config=config,
            assembler=assembler,
            ledger=ledger,
            memory=None,
            context=context,
            http_request=http_request,
            knowledge_base_id=knowledge_base_id,
            query=query,
            search_mode=search_mode,
            session_id=session_id,
            turn_id=turn_id,
            resume_thread_id=request.thread_id,
        ),
        media_type="text/event-stream",
    )


async def _chat_event_stream(
    *,
    initial_state: dict,
    config: dict,
    assembler: ContextAssembler,
    ledger: BudgetLedger,
    memory,
    context: RequestContext,
    http_request: Request,
    knowledge_base_id: str,
    query: str,
    search_mode: str,
    session_id: str,
    turn_id: str,
    resume_thread_id: str | None = None,
):
    """共享的 SSE 事件流：被 /chat 与 /chat/resume 复用。"""
    final_state = {}
    trace_service = await get_workflow_trace_service()
    workflow_run = await trace_service.start_run(
        context=context,
        session_id=session_id,
        turn_id=turn_id,
        knowledge_base_id=knowledge_base_id,
        query=query,
        search_mode=search_mode,
        request_id=getattr(http_request.state, "request_id", "-"),
        metadata={
            "thread_id": (config.get("configurable") or {}).get("thread_id", ""),
            "resumed_from": resume_thread_id,
        },
    )
    initial_state["workflow_run_id"] = workflow_run.run_id
    initial_state["request_id"] = getattr(http_request.state, "request_id", "-")
    initial_state["user_id"] = context.user_id
    initial_state["username"] = context.username
    run_finished = False

    logger.info(
        "chat_started",
        extra={
            "request_id": getattr(http_request.state, "request_id", "-"),
            "session_id": session_id,
            "turn_id": turn_id,
            "search_mode": search_mode,
            "knowledge_base_id": knowledge_base_id,
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "window_k": (
                memory.window_k
                if memory is not None
                else initial_state.get("window_k", 3)
            ),
            "episodic_count": (
                len(memory.episodic_memory)
                if memory is not None
                else len(initial_state.get("episodic_memory", []))
            ),
            "semantic_count": (
                len(memory.semantic_memory)
                if memory is not None
                else len(initial_state.get("semantic_memory", []))
            ),
            "resumed": resume_thread_id is not None,
        },
    )

    try:
        async for event in _stream_workflow_events(
            initial_state, config, resume_thread_id=resume_thread_id
        ):
            for node_name, state_update in event.items():
                node_started_at = time.time()
                final_state.update(state_update)
                _record_node_token_estimate(
                    ledger, node_name, state_update
                )
                await trace_service.record_node_success(
                    run=workflow_run,
                    node_name=node_name,
                    state_update=state_update,
                    started_at=node_started_at,
                    token_usage=ledger.snapshot().__dict__,
                )
                for tool_snapshot in state_update.get("_tool_runs", []):
                    tool_run = await trace_service.record_tool_run(
                        run=workflow_run,
                        node_name=node_name,
                        tool_snapshot=tool_snapshot,
                    )
                    if tool_run.status == "failed":
                        await trace_service.record_error_event(
                            error_code=tool_run.error_code or "TOOL_FAILED",
                            message=f"工具调用失败：{tool_run.tool_name}",
                            source="tool",
                            context=context,
                            request_id=getattr(http_request.state, "request_id", "-"),
                            session_id=session_id,
                            turn_id=turn_id,
                            run_id=workflow_run.run_id,
                            node_name=node_name,
                            path=str(http_request.url.path),
                            status_code=500,
                            details={
                                "tool_run_id": tool_run.tool_run_id,
                                "tool_name": tool_run.tool_name,
                                "reason": tool_run.error_message,
                            },
                        )
                for route_snapshot in state_update.get("_route_decisions", []):
                    await trace_service.record_route_decision(
                        run=workflow_run,
                        decision_snapshot=route_snapshot,
                    )

                public_state_update = _public_state_update(state_update)
                data = json.dumps(
                    {"step": node_name, "data": public_state_update},
                    ensure_ascii=False,
                )
                yield f"data: {data}\n\n"
                await asyncio.sleep(0.1)

        full_state = {**initial_state, **final_state}
        turn_record = await assembler.finalize(full_state, ledger)
        session_meta = await assembler.session_mgr.load_session(session_id)
        if session_meta is not None:
            await persist_completed_chat_turn(
                session_meta=session_meta,
                turn_record=turn_record,
                context=context,
                knowledge_base_id=knowledge_base_id,
                snapshot=ledger.snapshot(),
            )

        window_stats = assembler.window_mgr.get_window_stats(
            initial_state.get("episodic_memory", []) +
            initial_state.get("semantic_memory", [])
        )

        session_info = json.dumps(
            {
                "step": "__session__",
                "data": {
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "turn_number": turn_record.turn_number,
                    "token_usage": ledger.snapshot().__dict__,
                    "window_stats": window_stats,
                },
            },
            ensure_ascii=False,
        )
        yield f"data: {session_info}\n\n"
        await trace_service.finish_run(
            workflow_run,
            status=WorkflowRunStatus.SUCCEEDED.value,
            metadata={"turn_number": turn_record.turn_number},
        )
        run_finished = True

    except Exception as e:
        if isinstance(e, WorkflowPausedError):
            # 正常暂停（HITL）：将 run 标记为 PAUSED，下发暂停信号，
            # 等待人工输入后通过 /chat/resume 从断点续跑；不计入失败。
            pause_details = e.details
            await trace_service.finish_run(
                workflow_run,
                status=WorkflowRunStatus.PAUSED.value,
                metadata={"pause_node": pause_details.get("pause_node")},
            )
            run_finished = True
            yield json.dumps(
                {
                    "step": "__hitl_pause__",
                    "data": {
                        "thread_id": (config.get("configurable") or {}).get(
                            "thread_id", ""
                        ),
                        "pause_node": pause_details.get("pause_node"),
                        "prompt": pause_details.get("prompt"),
                        "resume_endpoint": "/api/chat/resume",
                        "human_input_field": "human_input",
                    },
                },
                ensure_ascii=False,
            )
            yield "data: [DONE]\n\n"
            return

        failure = _workflow_failure_snapshot(e)
        error_code = failure["error_code"]
        node_name = failure["node_name"]
        attempts = failure["attempts"]
        duration_ms = failure["duration_ms"]
        logger.exception(
            "chat_stream_failed",
            extra={
                "request_id": getattr(http_request.state, "request_id", "-"),
                "session_id": session_id,
                "turn_id": turn_id,
                "error_code": error_code,
                "node_name": node_name,
            },
        )
        run_finished = await _record_workflow_failure(
            trace_service=trace_service,
            workflow_run=workflow_run,
            context=context,
            request_id=getattr(http_request.state, "request_id", "-"),
            session_id=session_id,
            turn_id=turn_id,
            path=str(http_request.url.path),
            exc=e,
            failure=failure,
            run_finished=run_finished,
        )
        yield sse_error_event(
            code=error_code,
            message="任务执行失败",
            request_id=getattr(http_request.state, "request_id", "-"),
            details={
                "reason": str(e),
                "session_id": session_id,
                "turn_id": turn_id,
            },
        )

    yield "data: [DONE]\n\n"


async def _stream_workflow_events(initial_state: dict, config: dict, *, resume_thread_id: str | None = None):
    engine = create_workflow_engine()
    async for event in engine.astream(initial_state, config=config, resume_thread_id=resume_thread_id):
        yield event


def _record_node_token_estimate(
    ledger: BudgetLedger,
    node_name: str,
    state_update: dict,
) -> None:
    """Estimate token usage from a node update."""
    from app.utils.token_counter import count_tokens

    output_text = ""
    for key in ("final_report", "plan", "search_results", "critique"):
        val = state_update.get(key)
        if isinstance(val, str):
            output_text += val
        elif isinstance(val, list):
            output_text += " ".join(str(v) for v in val)

    if output_text:
        estimated = count_tokens(output_text)
        ledger.record(
            node_name=node_name,
            estimated=estimated,
            actual_input=estimated,
            actual_output=0,
        )


def _public_state_update(state_update: dict) -> dict:
    """Hide internal observability fields from the SSE payload."""
    return {key: value for key, value in state_update.items() if not key.startswith("_")}


def _workflow_failure_snapshot(exc: Exception) -> dict:
    """Normalize workflow failures for durable run/error trace records."""

    error_code = "CHAT_STREAM_FAILED"
    node_name = ""
    attempts = 1
    duration_ms = 0
    details = {
        "reason": str(exc),
        "attempts": attempts,
        "engine": settings.workflow_engine,
        "workflow_run_timeout_seconds": settings.workflow_run_timeout_seconds,
    }

    if isinstance(exc, WorkflowNodeExecutionError):
        error_code = exc.error_code
        node_name = exc.node_name
        attempts = exc.attempts
        duration_ms = exc.duration_ms
        details.update(
            {
                "attempts": attempts,
                "duration_ms": duration_ms,
                "node_name": node_name,
            }
        )
    elif isinstance(exc, WorkflowEngineExecutionError):
        error_code = exc.error_code
        node_name = exc.current_node
        duration_ms = exc.elapsed_ms
        details.update(
            {
                **exc.details,
                "duration_ms": duration_ms,
                "elapsed_ms": exc.elapsed_ms,
                "step_index": exc.step_index,
                "current_node": exc.current_node,
                "node_name": node_name,
            }
        )

    return {
        "error_code": error_code,
        "node_name": node_name,
        "attempts": attempts,
        "duration_ms": duration_ms,
        "details": details,
    }


async def _record_workflow_failure(
    *,
    trace_service,
    workflow_run,
    context: RequestContext,
    request_id: str,
    session_id: str,
    turn_id: str,
    path: str,
    exc: Exception,
    failure: dict,
    run_finished: bool,
) -> bool:
    error_code = failure["error_code"]
    node_name = failure["node_name"]
    attempts = failure["attempts"]
    duration_ms = failure["duration_ms"]
    cancelled = error_code == "WORKFLOW_RUN_CANCELLED"

    if node_name:
        await trace_service.record_node_failure(
            run=workflow_run,
            node_name=node_name,
            error_code=error_code,
            error_message=str(exc),
            duration_ms=duration_ms,
            attempts=attempts,
        )
    if not run_finished and not cancelled:
        await trace_service.finish_run(
            workflow_run,
            status=WorkflowRunStatus.FAILED.value,
            error_code=error_code,
            error_message=str(exc),
        )
        run_finished = True
    await trace_service.record_error_event(
        error_code=error_code,
        message="任务执行失败",
        source="workflow",
        context=context,
        request_id=request_id,
        session_id=session_id,
        turn_id=turn_id,
        run_id=workflow_run.run_id,
        node_name=node_name,
        path=path,
        status_code=500,
        details=failure["details"],
    )
    return run_finished

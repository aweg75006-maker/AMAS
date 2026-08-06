import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_assembler
from app.api.rate_limits import chat_rate_limit
from app.api.schemas import ChatRequest
from app.core.errors import sse_error_event
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.graph.engine_factory import create_workflow_engine
from app.graph.runtime import WorkflowNodeExecutionError
from app.services.chat_history_service import persist_completed_chat_turn
from app.services.knowledge_base_service import get_knowledge_base_service
from app.utils.budget_ledger import BudgetLedger
from app.utils.context_assembler import ContextAssembler


router = APIRouter()
logger = get_logger("iris.api.chat")


@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    http_request: Request,
    _rate_limit: None = Depends(chat_rate_limit),
):
    """
    Multi-turn research chat endpoint.

    The endpoint streams workflow node updates with SSE.
    """
    kb_service = await get_knowledge_base_service()
    knowledge_base_id = (
        request.knowledge_base_id
        or kb_service.default_knowledge_base_id()
    )
    kb = await kb_service.get_knowledge_base(knowledge_base_id)
    if kb is None and knowledge_base_id == kb_service.default_knowledge_base_id():
        kb = await kb_service.ensure_default_knowledge_base()
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

    session_id = initial_state["session_id"]
    turn_id = initial_state["turn_id"]
    request_id = getattr(http_request.state, "request_id", "-")

    config = {
        "configurable": {
            "thread_id": request.thread_id or turn_id,
            "session_id": session_id,
        }
    }

    return StreamingResponse(
        _chat_event_stream(
            initial_state=initial_state,
            config=config,
            assembler=assembler,
            ledger=ledger,
            memory=memory,
            http_request=http_request,
            knowledge_base_id=knowledge_base_id,
            query=request.query,
            search_mode=request.search_mode,
            session_id=session_id,
            turn_id=turn_id,
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
    http_request: Request,
    knowledge_base_id: str,
    query: str,
    search_mode: str,
    session_id: str,
    turn_id: str,
):
    """LangGraph SSE event stream for a single chat turn."""
    final_state = {}
    initial_state["request_id"] = getattr(http_request.state, "request_id", "-")

    logger.info(
        "chat_started",
        extra={
            "request_id": getattr(http_request.state, "request_id", "-"),
            "session_id": session_id,
            "turn_id": turn_id,
            "search_mode": search_mode,
            "knowledge_base_id": knowledge_base_id,
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
        },
    )

    try:
        async for event in _stream_workflow_events(initial_state, config):
            for node_name, state_update in event.items():
                final_state.update(state_update)
                _record_node_token_estimate(ledger, node_name, state_update)

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
    except Exception as e:
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


async def _stream_workflow_events(initial_state: dict, config: dict):
    engine = create_workflow_engine()
    async for event in engine.astream(initial_state, config=config):
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
    """Normalize a workflow failure for the SSE error payload."""

    error_code = "CHAT_STREAM_FAILED"
    node_name = ""
    attempts = 1
    duration_ms = 0
    details = {
        "reason": str(exc),
        "attempts": attempts,
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
    return {
        "error_code": error_code,
        "node_name": node_name,
        "attempts": attempts,
        "duration_ms": duration_ms,
        "details": details,
    }

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.api.context import RequestContext, get_request_context
from app.api.dependencies import CHECKPOINT_DB_PATH, get_assembler
from app.api.rate_limits import chat_rate_limit
from app.api.schemas import ChatRequest
from app.core.errors import sse_error_event
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.graph.graph import create_graph
from app.services.knowledge_base_service import get_knowledge_base_service
from app.utils.budget_ledger import BudgetLedger


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

    The endpoint streams LangGraph node updates with SSE.
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
        }
    }

    async def event_generator():
        final_state = {}

        logger.info(
            "chat_started",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "search_mode": request.search_mode,
                "knowledge_base_id": knowledge_base_id,
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "window_k": memory.window_k,
                "episodic_count": len(memory.episodic_memory),
                "semantic_count": len(memory.semantic_memory),
            },
        )

        try:
            async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as memory_saver:
                app = create_graph(memory=memory_saver)

                async for event in app.astream(initial_state, config=config):
                    for node_name, state_update in event.items():
                        final_state.update(state_update)
                        _record_node_token_estimate(
                            ledger, node_name, state_update
                        )

                        data = json.dumps(
                            {"step": node_name, "data": state_update},
                            ensure_ascii=False,
                        )
                        yield f"data: {data}\n\n"
                        await asyncio.sleep(0.1)

            full_state = {**initial_state, **final_state}
            turn_record = await assembler.finalize(full_state, ledger)

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
            logger.exception(
                "chat_stream_failed",
                extra={
                    "request_id": request_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                },
            )
            yield sse_error_event(
                code="CHAT_STREAM_FAILED",
                message="任务执行失败",
                request_id=request_id,
                details={"reason": str(e), "session_id": session_id, "turn_id": turn_id},
            )

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


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

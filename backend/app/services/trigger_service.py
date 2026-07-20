"""
被动触发研究运行器（headless）。

供 Webhook / Cron 触发的"无人值守"研究任务使用：在后台把一次完整研究跑完，
结束后（可选）把结果推送到飞书。

它复用了与 ``/chat`` 相同的 ``ContextAssembler`` / ``BudgetLedger`` /
``PythonWorkflowEngine`` / ``WorkflowTraceService``，但**不**通过 SSE 流式返回，
而是把最终报告收集起来，便于异步通知。
"""
from __future__ import annotations

import time
from typing import Any, Optional

from app.core.identity import RequestContext
from app.core.logging import get_logger
from app.graph.engine import WorkflowEngineExecutionError
from app.graph.engine_factory import create_workflow_engine
from app.models.domain import WorkflowRunStatus
from app.services.chat_history_service import persist_completed_chat_turn
from app.services.knowledge_base_service import get_knowledge_base_service
from app.services.workflow_trace_service import get_workflow_trace_service
from app.utils.budget_ledger import BudgetLedger
from app.api.dependencies import get_assembler
from app.utils.token_counter import count_tokens


logger = get_logger("iris.trigger.service")


async def run_research_and_notify(
    *,
    query: str,
    context: RequestContext,
    search_mode: str = "hybrid",
    knowledge_base_id: Optional[str] = None,
    session_id: Optional[str] = None,
    notify: bool = True,
    notify_webhook_url: Optional[str] = None,
    request_id: str = "",
    feishu_notifier=None,
) -> dict[str, Any]:
    """在后台跑完一次研究，并按需推送飞书通知。

    返回最终执行摘要（status / run_id / 报告 / 错误），便于调用方记录或轮询。
    """
    from app.integrations.feishu import FeishuNotifier

    # 1. 解析知识库（缺失则回退到默认知识库，仍缺失则失败并通知）。
    kb_service = await get_knowledge_base_service()
    kb_id = knowledge_base_id or kb_service.default_knowledge_base_id(context.tenant_id)
    kb = await kb_service.get_knowledge_base_for_tenant(kb_id, context.tenant_id)
    if kb is None and kb_id == kb_service.default_knowledge_base_id(context.tenant_id):
        kb = await kb_service.ensure_default_knowledge_base(
            tenant_id=context.tenant_id, created_by=context.user_id
        )
    if kb is None:
        msg = "知识库不存在，无法执行研究任务"
        logger.error("trigger_kb_missing", extra={"knowledge_base_id": kb_id})
        if notify:
            notifier = feishu_notifier or FeishuNotifier(notify_webhook_url)
            await notifier.send_card("研究任务失败", f"**研究问题**：{query}\n**原因**：{msg}")
        return {"status": "failed", "error": "KNOWLEDGE_BASE_NOT_FOUND", "final_report": ""}

    # 2. 装配初始状态（会话/记忆/预算）。
    assembler = await get_assembler()
    initial_state, ledger, _memory = await assembler.prepare(
        query=query, search_mode=search_mode, session_id=session_id
    )
    initial_state["knowledge_base_id"] = kb_id
    initial_state["tenant_id"] = context.tenant_id

    sid = initial_state["session_id"]
    tid = initial_state["turn_id"]

    # 3. 开启一次可追踪的 workflow run。
    trace_service = await get_workflow_trace_service()
    run = await trace_service.start_run(
        context=context,
        session_id=sid,
        turn_id=tid,
        knowledge_base_id=kb_id,
        query=query,
        search_mode=search_mode,
        request_id=request_id or "-",
        metadata={"source": "trigger", "notify": notify},
    )
    initial_state["workflow_run_id"] = run.run_id
    initial_state["request_id"] = request_id or "-"
    initial_state["user_id"] = context.user_id
    initial_state["username"] = context.username

    config = {"configurable": {"thread_id": tid, "session_id": sid}}
    final_state: dict[str, Any] = {}
    status = "succeeded"
    error: Optional[str] = None
    started_at = time.monotonic()

    # 4. 运行工作流引擎（无 SSE，收集最终状态）。
    try:
        engine = create_workflow_engine()
        async for event in engine.astream(initial_state, config=config):
            for node_name, state_update in event.items():
                final_state.update(state_update)
                _record_node_token_estimate(ledger, node_name, state_update)
                await trace_service.record_node_success(
                    run=run,
                    node_name=node_name,
                    state_update=state_update,
                    started_at=started_at,
                    token_usage=ledger.snapshot().__dict__,
                )

        full_state = {**initial_state, **final_state}
        turn_record = await assembler.finalize(full_state, ledger)
        try:
            session_meta = await assembler.session_mgr.load_session(sid)
            if session_meta is not None:
                await persist_completed_chat_turn(
                    session_meta=session_meta,
                    turn_record=turn_record,
                    context=context,
                    knowledge_base_id=kb_id,
                    snapshot=ledger.snapshot(),
                )
        except Exception as persist_exc:  # 归档失败不应影响整体状态
            logger.warning(
                "trigger_persist_failed",
                extra={"run_id": run.run_id, "error": str(persist_exc)},
            )

        await trace_service.finish_run(
            run,
            status=WorkflowRunStatus.SUCCEEDED.value,
            metadata={"turn_number": turn_record.turn_number},
        )
    except Exception as exc:
        status = "failed"
        error = str(exc)
        logger.exception(
            "trigger_research_failed", extra={"run_id": run.run_id, "error": error}
        )
        code = exc.error_code if isinstance(exc, WorkflowEngineExecutionError) else "TRIGGER_RESEARCH_FAILED"
        await trace_service.finish_run(
            run,
            status=WorkflowRunStatus.FAILED.value,
            error_code=code,
            error_message=error,
        )

    final_report = final_state.get("final_report", "")

    # 5. 飞书通知（best-effort）。
    if notify:
        notifier = feishu_notifier or FeishuNotifier(notify_webhook_url)
        if notifier.enabled:
            if status == "succeeded":
                body = (final_report or "（无报告内容）")[:1500]
                md = (
                    f"**研究问题**：{query}\n"
                    f"**状态**：✅ 成功\n"
                    f"**run_id**：`{run.run_id}`\n\n"
                    f"**报告摘要**：\n{body}"
                )
            else:
                md = (
                    f"**研究问题**：{query}\n"
                    f"**状态**：❌ 失败\n"
                    f"**run_id**：`{run.run_id}`\n"
                    f"**错误**：{error}"
                )
            await notifier.send_card(
                f"研究任务{'完成' if status == 'succeeded' else '失败'}", md
            )
        else:
            logger.info("trigger_notify_skipped", extra={"run_id": run.run_id})

    return {
        "status": status,
        "run_id": run.run_id,
        "session_id": sid,
        "turn_id": tid,
        "final_report": final_report,
        "error": error,
    }


def _record_node_token_estimate(
    ledger: BudgetLedger, node_name: str, state_update: dict
) -> None:
    """估算节点 Token 消耗（与 /chat 的记账口径一致）。"""
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

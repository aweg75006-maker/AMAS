import pytest

from app.models.domain import (
    ErrorEventRecord,
    WorkflowNodeRunRecord,
    WorkflowRunRecord,
    WorkflowToolRunRecord,
)
from app.repositories.workflow_trace_repository import PostgresWorkflowTraceRepository
from tests.test_knowledge_base_repository import FakeConnection, FakePool


@pytest.mark.asyncio
async def test_postgres_workflow_trace_repository_save_methods():
    conn = FakeConnection()
    repository = PostgresWorkflowTraceRepository("postgresql://example")
    repository._pool = FakePool(conn)

    await repository.save_workflow_run(
        WorkflowRunRecord(
            run_id="run_1",
            tenant_id="tenant_1",
            query="hello",
            metadata={"thread_id": "turn_1"},
        )
    )
    await repository.save_node_run(
        WorkflowNodeRunRecord(
            node_run_id="node_1",
            run_id="run_1",
            node_name="writer",
            tenant_id="tenant_1",
            output_summary="done",
            token_usage={"estimated": 1},
        )
    )
    await repository.save_tool_run(
        WorkflowToolRunRecord(
            tool_run_id="tool_1",
            run_id="run_1",
            node_name="researcher",
            tool_name="web.search",
            tenant_id="tenant_1",
            status="failed",
            input_summary="hello",
            error_code="TOOL_FAILED",
            error_message="boom",
            metadata={"attempts": 2},
        )
    )
    await repository.save_error_event(
        ErrorEventRecord(
            error_event_id="err_1",
            error_code="TEST_ERROR",
            message="failed",
            tenant_id="tenant_1",
            details={"reason": "boom"},
        )
    )

    joined_sql = "\n".join(sql for sql, _args in conn.executed)
    assert "INSERT INTO workflow_runs" in joined_sql
    assert "INSERT INTO workflow_node_runs" in joined_sql
    assert "INSERT INTO workflow_tool_runs" in joined_sql
    assert "INSERT INTO error_events" in joined_sql
    assert conn.executed[0][1][16] == '{"thread_id": "turn_1"}'
    assert conn.executed[1][1][12] == '{"estimated": 1}'
    assert conn.executed[2][1][15] == '{"attempts": 2}'
    assert conn.executed[3][1][15] == '{"reason": "boom"}'


@pytest.mark.asyncio
async def test_postgres_workflow_trace_repository_lists_runs():
    conn = FakeConnection()
    conn.rows["fetch"] = [
        {
            "run_id": "run_1",
            "tenant_id": "tenant_1",
            "user_id": "user_1",
            "username": "owner",
            "session_id": "iris_1",
            "turn_id": "turn_1",
            "knowledge_base_id": "kb_1",
            "request_id": "req_1",
            "query": "hello",
            "search_mode": "hybrid",
            "status": "succeeded",
            "started_at": 1.0,
            "finished_at": 2.0,
            "duration_ms": 1000,
            "error_code": "",
            "error_message": "",
            "metadata": {"thread_id": "turn_1"},
        }
    ]
    repository = PostgresWorkflowTraceRepository("postgresql://example")
    repository._pool = FakePool(conn)

    runs = await repository.list_workflow_runs("tenant_1", limit=10)

    assert len(runs) == 1
    assert runs[0].run_id == "run_1"
    assert "tenant_id = $1" in conn.last_fetch_sql
    assert conn.last_fetch_args == ("tenant_1", 10)


@pytest.mark.asyncio
async def test_postgres_workflow_trace_repository_lists_tool_runs():
    conn = FakeConnection()
    conn.rows["fetch"] = [
        {
            "tool_run_id": "tool_1",
            "run_id": "run_1",
            "node_name": "researcher",
            "tool_name": "rag.retrieve",
            "tenant_id": "tenant_1",
            "session_id": "iris_1",
            "turn_id": "turn_1",
            "status": "succeeded",
            "started_at": 1.0,
            "finished_at": 2.0,
            "duration_ms": 1000,
            "input_summary": "hello",
            "output_summary": "doc",
            "error_code": "",
            "error_message": "",
            "metadata": {"attempts": 1},
        }
    ]
    repository = PostgresWorkflowTraceRepository("postgresql://example")
    repository._pool = FakePool(conn)

    tool_runs = await repository.list_tool_runs("run_1")

    assert len(tool_runs) == 1
    assert tool_runs[0].tool_name == "rag.retrieve"
    assert tool_runs[0].metadata["attempts"] == 1
    assert "workflow_tool_runs" in conn.last_fetch_sql
    assert conn.last_fetch_args == ("run_1",)

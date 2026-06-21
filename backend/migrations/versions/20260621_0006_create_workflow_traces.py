"""create workflow traces and error events

Revision ID: 20260621_0006
Revises: 20260621_0005
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260621_0006"
down_revision: Union[str, None] = "20260621_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            run_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            turn_id TEXT NOT NULL DEFAULT '',
            knowledge_base_id TEXT NOT NULL DEFAULT '',
            request_id TEXT NOT NULL DEFAULT '',
            query TEXT NOT NULL DEFAULT '',
            search_mode TEXT NOT NULL DEFAULT 'hybrid',
            status TEXT NOT NULL DEFAULT 'running',
            started_at DOUBLE PRECISION NOT NULL,
            finished_at DOUBLE PRECISION,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            error_code TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_tenant_started
            ON workflow_runs (tenant_id, started_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_session
            ON workflow_runs (session_id, started_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_node_runs (
            node_run_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
            node_name TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '',
            turn_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'succeeded',
            started_at DOUBLE PRECISION NOT NULL,
            finished_at DOUBLE PRECISION NOT NULL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            input_summary TEXT NOT NULL DEFAULT '',
            output_summary TEXT NOT NULL DEFAULT '',
            token_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_code TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_node_runs_run
            ON workflow_node_runs (run_id, started_at ASC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS error_events (
            error_event_id TEXT PRIMARY KEY,
            error_code TEXT NOT NULL,
            message TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'api',
            severity TEXT NOT NULL DEFAULT 'error',
            tenant_id TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT '',
            request_id TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            turn_id TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            node_name TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL DEFAULT '',
            status_code INTEGER NOT NULL DEFAULT 500,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at DOUBLE PRECISION NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_error_events_tenant_created
            ON error_events (tenant_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_error_events_request
            ON error_events (request_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS error_events;")
    op.execute("DROP TABLE IF EXISTS workflow_node_runs;")
    op.execute("DROP TABLE IF EXISTS workflow_runs;")

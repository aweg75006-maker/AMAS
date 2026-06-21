"""create workflow tool runs

Revision ID: 20260621_0007
Revises: 20260621_0006
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260621_0007"
down_revision: Union[str, None] = "20260621_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_tool_runs (
            tool_run_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
            node_name TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '',
            turn_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'succeeded',
            started_at DOUBLE PRECISION NOT NULL,
            finished_at DOUBLE PRECISION NOT NULL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            input_summary TEXT NOT NULL DEFAULT '',
            output_summary TEXT NOT NULL DEFAULT '',
            error_code TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_tool_runs_run
            ON workflow_tool_runs (run_id, started_at ASC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_tool_runs_tenant_started
            ON workflow_tool_runs (tenant_id, started_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_tool_runs_tool_started
            ON workflow_tool_runs (tool_name, started_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_tool_runs;")

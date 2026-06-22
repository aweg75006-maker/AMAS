"""create workflow route decisions

Revision ID: 20260622_0008
Revises: 20260621_0007
Create Date: 2026-06-22
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260622_0008"
down_revision: Union[str, None] = "20260621_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_route_decisions (
            decision_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '',
            turn_id TEXT NOT NULL DEFAULT '',
            created_at DOUBLE PRECISION NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_route_decisions_run
            ON workflow_route_decisions (run_id, created_at ASC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_route_decisions_tenant_created
            ON workflow_route_decisions (tenant_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_route_decisions_edge
            ON workflow_route_decisions (from_node, to_node)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_route_decisions;")

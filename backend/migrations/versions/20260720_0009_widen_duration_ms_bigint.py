"""widen duration_ms to BIGINT

Revision ID: 20260720_0009
Revises: 20260622_0008
Create Date: 2026-07-20

duration_ms 在 WorkflowNodeRunRecord / WorkflowToolRunRecord 中以毫秒为单位的
耗时写入。当调用方误用 time.monotonic()（与 time.time() 不同 epoch）作为
started_at 时，会算出约 1.78e12ms 的伪 duration，超过 INTEGER 上限（2,147,483,647）
导致 Postgres 插入报错 "value out of int32 range"。即便修正调用方，单个运行超过
约 24.8 天的极端场景仍会溢出，因此将三张 trace 表的 duration_ms 统一放宽为 BIGINT。
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260720_0009"
down_revision: Union[str, None] = "20260622_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("workflow_runs", "workflow_node_runs", "workflow_tool_runs")


def upgrade() -> None:
    for table in TABLES:
        op.execute(
            f"ALTER TABLE IF EXISTS {table} "
            "ALTER COLUMN duration_ms TYPE BIGINT"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(
            f"ALTER TABLE IF EXISTS {table} "
            "ALTER COLUMN duration_ms TYPE INTEGER"
        )

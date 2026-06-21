"""create chat history tables

Revision ID: 20260621_0005
Revises: 20260621_0004
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260621_0005"
down_revision: Union[str, None] = "20260621_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT '',
            knowledge_base_id TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            turns_count INTEGER NOT NULL DEFAULT 0,
            total_budget INTEGER NOT NULL DEFAULT 128000,
            total_estimated_tokens INTEGER NOT NULL DEFAULT 0,
            total_actual_tokens INTEGER NOT NULL DEFAULT 0,
            compression_savings INTEGER NOT NULL DEFAULT 0,
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            last_active DOUBLE PRECISION NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_tenant_updated
            ON chat_sessions (tenant_id, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
            ON chat_sessions (user_id, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_turns (
            turn_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES chat_sessions(session_id)
                ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT '',
            knowledge_base_id TEXT NOT NULL DEFAULT '',
            turn_number INTEGER NOT NULL DEFAULT 0,
            query TEXT NOT NULL DEFAULT '',
            search_mode TEXT NOT NULL DEFAULT 'hybrid',
            plan JSONB NOT NULL DEFAULT '[]'::jsonb,
            search_results JSONB NOT NULL DEFAULT '[]'::jsonb,
            final_report TEXT NOT NULL DEFAULT '',
            critique TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT '',
            token_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at DOUBLE PRECISION NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_turns_session_number
            ON chat_turns (session_id, turn_number DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_turns_tenant_created
            ON chat_turns (tenant_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_turns;")
    op.execute("DROP TABLE IF EXISTS chat_sessions;")

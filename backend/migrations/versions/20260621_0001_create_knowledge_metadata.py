"""create knowledge metadata tables

Revision ID: 20260621_0001
Revises:
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260621_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_bases (
            knowledge_base_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private',
            embedding_model TEXT NOT NULL,
            chunking_strategy TEXT NOT NULL,
            created_by TEXT NOT NULL DEFAULT '',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_knowledge_bases_tenant_updated
            ON knowledge_bases (tenant_id, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_documents (
            document_id TEXT PRIMARY KEY,
            knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(knowledge_base_id)
                ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL DEFAULT '',
            content_type TEXT NOT NULL DEFAULT '',
            size_bytes BIGINT NOT NULL DEFAULT 0,
            file_hash TEXT NOT NULL DEFAULT '',
            storage_path TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'uploaded',
            parser_version TEXT NOT NULL DEFAULT '',
            chunk_count INTEGER NOT NULL DEFAULT 0,
            page_count INTEGER,
            error_message TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT '',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_knowledge_documents_kb_created
            ON knowledge_documents (knowledge_base_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_documents;")
    op.execute("DROP TABLE IF EXISTS knowledge_bases;")

"""add username to users

Revision ID: 20260621_0003
Revises: 20260621_0002
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260621_0003"
down_revision: Union[str, None] = "20260621_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT NOT NULL DEFAULT ''")
    op.execute(
        """
        UPDATE users
        SET username = split_part(email, '@', 1)
        WHERE username = ''
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users (username)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_username")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS username")

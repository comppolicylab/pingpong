"""add lecture slide context file metadata

Revision ID: f6a8b0c2d4e6
Revises: e5f7a9b1c3d5
Create Date: 2026-08-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a8b0c2d4e6"
down_revision: str | None = "e5f7a9b1c3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("lecture_slide_additional_context_files") as batch_op:
        batch_op.add_column(
            sa.Column("file_kind", sa.String(), server_default="other", nullable=False)
        )
        batch_op.add_column(
            sa.Column("usage_mode", sa.String(), server_default="guide", nullable=False)
        )
        batch_op.add_column(sa.Column("usage_note", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("lecture_slide_additional_context_files") as batch_op:
        batch_op.drop_column("usage_note")
        batch_op.drop_column("usage_mode")
        batch_op.drop_column("file_kind")

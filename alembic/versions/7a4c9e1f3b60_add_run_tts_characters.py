"""Add run TTS characters.

Revision ID: 7a4c9e1f3b60
Revises: 5d8e2b7c1a40
"""

from alembic import op
import sqlalchemy as sa

revision = "7a4c9e1f3b60"
down_revision = "5d8e2b7c1a40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column("runs", sa.Column("tts_characters", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "tts_characters")

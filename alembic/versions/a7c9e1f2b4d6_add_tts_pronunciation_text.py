"""add tts pronunciation text

Revision ID: a7c9e1f2b4d6
Revises: f6a8b0c2d4e6
Create Date: 2026-08-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c9e1f2b4d6"
down_revision: str | None = "f6a8b0c2d4e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column(
        "lecture_video_narrations", sa.Column("tts_text", sa.Text(), nullable=True)
    )
    op.add_column(
        "lecture_slide_narrations", sa.Column("tts_text", sa.Text(), nullable=True)
    )
    op.add_column(
        "lecture_slide_pages",
        sa.Column("narration_tts_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "lecture_slide_translation_pages",
        sa.Column("narration_tts_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lecture_slide_translation_pages", "narration_tts_text")
    op.drop_column("lecture_slide_pages", "narration_tts_text")
    op.drop_column("lecture_slide_narrations", "tts_text")
    op.drop_column("lecture_video_narrations", "tts_text")

"""Translate lecture feedback.

Revision ID: c9e1a3b5d7f9
Revises: b8d0f2a4c6e8
"""

from alembic import op
import sqlalchemy as sa

revision = "c9e1a3b5d7f9"
down_revision = "b8d0f2a4c6e8"
branch_labels = None
depends_on = None


def upgrade():
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on

    op.create_table(
        "lecture_slide_translation_narrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "translation_id",
            sa.Integer(),
            sa.ForeignKey("lecture_slide_translations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_narration_id",
            sa.Integer(),
            sa.ForeignKey("lecture_slide_narrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tts_text", sa.Text(), nullable=True),
        sa.Column(
            "stored_object_id",
            sa.Integer(),
            sa.ForeignKey(
                "lecture_slide_narration_stored_objects.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.UniqueConstraint("translation_id", "source_narration_id"),
    )
    op.create_index(
        "ix_lecture_slide_translation_narrations_translation_id",
        "lecture_slide_translation_narrations",
        ["translation_id"],
    )
    op.create_index(
        "ix_lecture_slide_translation_narrations_stored_object_id",
        "lecture_slide_translation_narrations",
        ["stored_object_id"],
    )


def downgrade():
    op.drop_table("lecture_slide_translation_narrations")

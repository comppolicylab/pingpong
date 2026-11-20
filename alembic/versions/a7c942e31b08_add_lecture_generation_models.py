"""Add lecture material generation models and answer evaluation instructions.

Revision ID: a7c942e31b08
Revises: e8a21f4d6c90
"""

from alembic import op
import sqlalchemy as sa

revision = "a7c942e31b08"
down_revision = "e8a21f4d6c90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assistants", sa.Column("lecture_check_instructions", sa.Text(), nullable=True)
    )
    op.add_column(
        "assistants", sa.Column("lecture_generation_model", sa.String(), nullable=True)
    )
    op.add_column(
        "assistants", sa.Column("lecture_gemini_model", sa.String(), nullable=True)
    )

    assistants = sa.table(
        "assistants", sa.column("interaction_mode"), sa.column("lecture_gemini_model")
    )
    op.execute(
        assistants.update()
        .where(assistants.c.interaction_mode == "LECTURE_VIDEO")
        .values(lecture_gemini_model="gemini-3.6-flash")
    )


def downgrade() -> None:
    op.drop_column("assistants", "lecture_check_instructions")
    op.drop_column("assistants", "lecture_gemini_model")
    op.drop_column("assistants", "lecture_generation_model")

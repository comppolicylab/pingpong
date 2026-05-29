"""Add lecture slide runtime state

Revision ID: 8fb2a14e9c6d
Revises: 5b9c0d1e2f3a
Create Date: 2026-05-29 15:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8fb2a14e9c6d"
down_revision: Union[str, None] = "5b9c0d1e2f3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


interactive_lesson_session_state_enum = sa.Enum(
    "PLAYING",
    "AWAITING_ANSWER",
    "AWAITING_POST_ANSWER_RESUME",
    "COMPLETED",
    name="interactivelessonsessionstate",
)
interactive_lesson_interaction_event_type_enum = sa.Enum(
    "SESSION_INITIALIZED",
    "QUESTION_PRESENTED",
    "ANSWER_SUBMITTED",
    "LESSON_RESUMED",
    "LESSON_PAUSED",
    "LESSON_SEEKED",
    "LESSON_ENDED",
    "SESSION_COMPLETED",
    name="interactivelessoninteractioneventtype",
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.create_table(
        "lecture_slide_thread_states",
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            interactive_lesson_session_state_enum,
            server_default="PLAYING",
            nullable=False,
        ),
        sa.Column("current_question_id", sa.Integer(), nullable=True),
        sa.Column("active_option_id", sa.Integer(), nullable=True),
        sa.Column(
            "last_known_offset_ms", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "furthest_offset_ms", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "last_chat_context_end_ms",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("controller_session_id", sa.String(), nullable=True),
        sa.Column("controller_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "controller_lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["active_option_id"],
            ["lecture_slide_question_options.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["controller_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["current_question_id"],
            ["lecture_slide_questions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("thread_id"),
    )

    op.create_table(
        "lecture_slide_interactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("event_index", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "event_type", interactive_lesson_interaction_event_type_enum, nullable=False
        ),
        sa.Column("question_id", sa.Integer(), nullable=True),
        sa.Column("option_id", sa.Integer(), nullable=True),
        sa.Column("offset_ms", sa.Integer(), nullable=True),
        sa.Column("from_offset_ms", sa.Integer(), nullable=True),
        sa.Column("to_offset_ms", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["option_id"], ["lecture_slide_question_options.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["lecture_slide_questions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", "event_index"),
        sa.UniqueConstraint("thread_id", "idempotency_key"),
    )
    op.create_index(
        "lecture_slide_interaction_thread_created_idx",
        "lecture_slide_interactions",
        ["thread_id", "created"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "lecture_slide_interaction_thread_created_idx",
        table_name="lecture_slide_interactions",
    )
    op.drop_table("lecture_slide_interactions")
    op.drop_table("lecture_slide_thread_states")
    interactive_lesson_interaction_event_type_enum.drop(op.get_bind(), checkfirst=True)
    interactive_lesson_session_state_enum.drop(op.get_bind(), checkfirst=True)

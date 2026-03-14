"""Lecture video runtime control and history

Revision ID: 0a1c5d9b7e44
Revises: 4db0bf59f8c2
Create Date: 2026-03-13 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0a1c5d9b7e44"
down_revision: Union[str, None] = "4db0bf59f8c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


lecture_video_session_state_enum = sa.Enum(
    "PLAYING",
    "AWAITING_ANSWER",
    "AWAITING_POST_ANSWER_RESUME",
    "COMPLETED",
    name="lecturevideosessionstate",
)
lecture_video_interaction_event_type_enum = sa.Enum(
    "SESSION_INITIALIZED",
    "QUESTION_PRESENTED",
    "ANSWER_SUBMITTED",
    "VIDEO_RESUMED",
    "VIDEO_PAUSED",
    "VIDEO_SEEKED",
    "VIDEO_ENDED",
    "SESSION_COMPLETED",
    name="lecturevideointeractioneventtype",
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.create_table(
        "lecture_video_thread_states",
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            lecture_video_session_state_enum,
            server_default="PLAYING",
            nullable=False,
        ),
        sa.Column("current_question_id", sa.Integer(), nullable=True),
        sa.Column("active_option_id", sa.Integer(), nullable=True),
        sa.Column(
            "last_known_offset_ms", sa.Integer(), server_default="0", nullable=False
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
            ["lecture_video_question_options.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["controller_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["current_question_id"], ["lecture_video_questions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("thread_id"),
    )

    op.create_table(
        "lecture_video_interactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("event_index", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "event_type", lecture_video_interaction_event_type_enum, nullable=False
        ),
        sa.Column("question_id", sa.Integer(), nullable=True),
        sa.Column("option_id", sa.Integer(), nullable=True),
        sa.Column("offset_ms", sa.Integer(), nullable=True),
        sa.Column("from_offset_ms", sa.Integer(), nullable=True),
        sa.Column("to_offset_ms", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["option_id"], ["lecture_video_question_options.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["lecture_video_questions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", "event_index"),
        sa.UniqueConstraint("thread_id", "idempotency_key"),
    )
    op.create_index(
        "lecture_video_interaction_thread_created_idx",
        "lecture_video_interactions",
        ["thread_id", "created"],
        unique=False,
    )

    threads = sa.table(
        "threads",
        sa.column("id", sa.Integer()),
        sa.column("interaction_mode", sa.String()),
        sa.column("lecture_video_id", sa.Integer()),
    )
    questions = sa.table(
        "lecture_video_questions",
        sa.column("id", sa.Integer()),
        sa.column("lecture_video_id", sa.Integer()),
        sa.column("position", sa.Integer()),
    )
    thread_states = sa.table(
        "lecture_video_thread_states",
        sa.column("thread_id", sa.Integer()),
        sa.column("state", lecture_video_session_state_enum),
        sa.column("current_question_id", sa.Integer()),
        sa.column("last_known_offset_ms", sa.Integer()),
        sa.column("version", sa.Integer()),
    )
    interactions = sa.table(
        "lecture_video_interactions",
        sa.column("thread_id", sa.Integer()),
        sa.column("event_index", sa.Integer()),
        sa.column("event_type", lecture_video_interaction_event_type_enum),
    )

    first_question_id = (
        sa.select(questions.c.id)
        .where(questions.c.lecture_video_id == threads.c.lecture_video_id)
        .order_by(questions.c.position)
        .limit(1)
        .scalar_subquery()
    )
    state_value = sa.cast(
        sa.case(
            (
                first_question_id.is_not(None),
                sa.literal("PLAYING"),
            ),
            else_=sa.literal("COMPLETED"),
        ),
        lecture_video_session_state_enum,
    )
    session_initialized_event_type = sa.cast(
        sa.literal("SESSION_INITIALIZED"),
        lecture_video_interaction_event_type_enum,
    )

    op.execute(
        sa.insert(thread_states).from_select(
            [
                "thread_id",
                "state",
                "current_question_id",
                "last_known_offset_ms",
                "version",
            ],
            sa.select(
                threads.c.id,
                state_value,
                first_question_id,
                sa.literal(0),
                sa.literal(1),
            ).where(
                threads.c.interaction_mode == "LECTURE_VIDEO",
                threads.c.lecture_video_id.is_not(None),
                ~sa.exists(
                    sa.select(1).where(thread_states.c.thread_id == threads.c.id)
                ),
            ),
        )
    )

    op.execute(
        sa.insert(interactions).from_select(
            ["thread_id", "event_index", "event_type"],
            sa.select(
                threads.c.id,
                sa.literal(1),
                session_initialized_event_type,
            ).where(
                threads.c.interaction_mode == "LECTURE_VIDEO",
                threads.c.lecture_video_id.is_not(None),
                ~sa.exists(
                    sa.select(1).where(
                        interactions.c.thread_id == threads.c.id,
                        interactions.c.event_index == 1,
                    )
                ),
            ),
        )
    )


def downgrade() -> None:
    op.drop_index(
        "lecture_video_interaction_thread_created_idx",
        table_name="lecture_video_interactions",
    )
    op.drop_table("lecture_video_interactions")
    op.drop_table("lecture_video_thread_states")
    lecture_video_interaction_event_type_enum.drop(op.get_bind(), checkfirst=True)
    lecture_video_session_state_enum.drop(op.get_bind(), checkfirst=True)

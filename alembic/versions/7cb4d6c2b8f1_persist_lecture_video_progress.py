"""Persist lecture video furthest offset progress

Revision ID: 7cb4d6c2b8f1
Revises: 4d7f7f5c1c12
Create Date: 2026-03-19 14:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7cb4d6c2b8f1"
down_revision: Union[str, None] = "4d7f7f5c1c12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


lecture_video_thread_states = sa.table(
    "lecture_video_thread_states",
    sa.Column("thread_id", sa.Integer()),
    sa.Column("last_known_offset_ms", sa.Integer()),
    sa.Column("furthest_offset_ms", sa.Integer()),
)
lecture_video_interactions = sa.table(
    "lecture_video_interactions",
    sa.Column("thread_id", sa.Integer()),
    sa.Column("offset_ms", sa.Integer()),
    sa.Column("from_offset_ms", sa.Integer()),
    sa.Column("to_offset_ms", sa.Integer()),
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.add_column(
        "lecture_video_thread_states",
        sa.Column(
            "furthest_offset_ms", sa.Integer(), nullable=False, server_default="0"
        ),
    )

    bind = op.get_bind()
    offset_ms = sa.func.coalesce(lecture_video_interactions.c.offset_ms, 0)
    from_offset_ms = sa.func.coalesce(lecture_video_interactions.c.from_offset_ms, 0)
    to_offset_ms = sa.func.coalesce(lecture_video_interactions.c.to_offset_ms, 0)
    last_known_offset_ms = sa.func.coalesce(
        lecture_video_thread_states.c.last_known_offset_ms, 0
    )
    row_furthest_offset = sa.case(
        (
            sa.and_(
                offset_ms >= from_offset_ms,
                offset_ms >= to_offset_ms,
            ),
            offset_ms,
        ),
        (from_offset_ms >= to_offset_ms, from_offset_ms),
        else_=to_offset_ms,
    )
    interaction_furthest_offset_ms = sa.select(
        sa.func.coalesce(sa.func.max(row_furthest_offset), 0)
    ).where(
        lecture_video_interactions.c.thread_id
        == lecture_video_thread_states.c.thread_id
    )

    bind.execute(
        lecture_video_thread_states.update().values(
            furthest_offset_ms=sa.case(
                (
                    last_known_offset_ms
                    >= interaction_furthest_offset_ms.scalar_subquery(),
                    last_known_offset_ms,
                ),
                else_=interaction_furthest_offset_ms.scalar_subquery(),
            )
        )
    )


def downgrade() -> None:
    op.drop_column("lecture_video_thread_states", "furthest_offset_ms")

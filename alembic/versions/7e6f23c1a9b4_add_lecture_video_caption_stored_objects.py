"""add lecture video caption stored objects

Revision ID: 7e6f23c1a9b4
Revises: 4a9d7c3e2f10
Create Date: 2026-05-21 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7e6f23c1a9b4"
down_revision: Union[str, None] = "4a9d7c3e2f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.create_table(
        "lecture_video_caption_stored_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("content_length", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.add_column(
        "lecture_videos",
        sa.Column("caption_stored_object_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_lecture_videos_caption_stored_object_id",
        "lecture_videos",
        "lecture_video_caption_stored_objects",
        ["caption_stored_object_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_lecture_videos_caption_stored_object_id",
        "lecture_videos",
        type_="foreignkey",
    )
    op.drop_column("lecture_videos", "caption_stored_object_id")
    op.drop_table("lecture_video_caption_stored_objects")

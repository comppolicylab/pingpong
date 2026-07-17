"""add lecture slide mixed media

Revision ID: c8f2d4e6a1b3
Revises: b7e1c0d2f3a5
Create Date: 2026-07-17 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c8f2d4e6a1b3"
down_revision: Union[str, None] = "b7e1c0d2f3a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


lecture_slide_content_kind = sa.Enum(
    "SLIDE", "IMAGE", "GIF", "VIDEO", name="lectureslidecontentkind"
)
lecture_slide_content_kind_column = lecture_slide_content_kind.with_variant(
    postgresql.ENUM(
        "SLIDE",
        "IMAGE",
        "GIF",
        "VIDEO",
        name="lectureslidecontentkind",
        create_type=False,
    ),
    "postgresql",
)


def upgrade() -> None:
    lecture_slide_content_kind.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "lecture_slide_decks",
        sa.Column(
            "source_page_count", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.execute("UPDATE lecture_slide_decks SET source_page_count = slide_count")
    op.create_table(
        "lecture_slide_media_stored_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("uploader_id", sa.Integer(), nullable=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("content_length", sa.Integer(), server_default="0", nullable=False),
        sa.Column("content_kind", lecture_slide_content_kind_column, nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("width_px", sa.Integer(), nullable=True),
        sa.Column("height_px", sa.Integer(), nullable=True),
        sa.Column("created", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"]),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(
        "ix_lecture_slide_media_stored_objects_class_id",
        "lecture_slide_media_stored_objects",
        ["class_id"],
    )
    op.create_index(
        "ix_lecture_slide_media_stored_objects_uploader_id",
        "lecture_slide_media_stored_objects",
        ["uploader_id"],
    )
    with op.batch_alter_table("lecture_slide_pages") as batch_op:
        batch_op.add_column(
            sa.Column(
                "content_kind",
                lecture_slide_content_kind_column,
                server_default="SLIDE",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("source_page_number", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("media_stored_object_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_ls_pages_media_stored_object_id",
            "lecture_slide_media_stored_objects",
            ["media_stored_object_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_lecture_slide_pages_media_stored_object_id",
        "lecture_slide_pages",
        ["media_stored_object_id"],
    )
    op.execute(
        "UPDATE lecture_slide_pages SET source_page_number = position WHERE content_kind = 'SLIDE'"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lecture_slide_pages_media_stored_object_id",
        table_name="lecture_slide_pages",
    )
    with op.batch_alter_table("lecture_slide_pages") as batch_op:
        batch_op.drop_constraint(
            "fk_ls_pages_media_stored_object_id", type_="foreignkey"
        )
        batch_op.drop_column("media_stored_object_id")
        batch_op.drop_column("source_page_number")
        batch_op.drop_column("content_kind")
    op.drop_index(
        "ix_lecture_slide_media_stored_objects_uploader_id",
        table_name="lecture_slide_media_stored_objects",
    )
    op.drop_index(
        "ix_lecture_slide_media_stored_objects_class_id",
        table_name="lecture_slide_media_stored_objects",
    )
    op.drop_table("lecture_slide_media_stored_objects")
    op.drop_column("lecture_slide_decks", "source_page_count")
    lecture_slide_content_kind.drop(op.get_bind(), checkfirst=True)

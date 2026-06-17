"""add lecture slide additional context files

Revision ID: 17f9db8bc1a2
Revises: 0a1b2c3d4e5f
Create Date: 2026-06-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "17f9db8bc1a2"
down_revision: Union[str, None] = "0a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on

    op.create_table(
        "lecture_slide_additional_context_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecture_slide_deck_id", sa.Integer(), nullable=True),
        sa.Column("file_object_id", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("uploader_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("content_length", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["file_object_id"],
            ["files.id"],
            name="fk_ls_additional_context_file_object_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lecture_slide_deck_id"],
            ["lecture_slide_decks.id"],
            name="fk_ls_additional_context_deck_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploader_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_lecture_slide_additional_context_files_class_id"),
        "lecture_slide_additional_context_files",
        ["class_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lecture_slide_additional_context_files_file_object_id"),
        "lecture_slide_additional_context_files",
        ["file_object_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lecture_slide_additional_context_files_lecture_slide_deck_id"),
        "lecture_slide_additional_context_files",
        ["lecture_slide_deck_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lecture_slide_additional_context_files_uploader_id"),
        "lecture_slide_additional_context_files",
        ["uploader_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_lecture_slide_additional_context_files_uploader_id"),
        table_name="lecture_slide_additional_context_files",
    )
    op.drop_index(
        op.f("ix_lecture_slide_additional_context_files_lecture_slide_deck_id"),
        table_name="lecture_slide_additional_context_files",
    )
    op.drop_index(
        op.f("ix_lecture_slide_additional_context_files_file_object_id"),
        table_name="lecture_slide_additional_context_files",
    )
    op.drop_index(
        op.f("ix_lecture_slide_additional_context_files_class_id"),
        table_name="lecture_slide_additional_context_files",
    )
    op.drop_table("lecture_slide_additional_context_files")

"""Add lecture slide chat and captions fields

Revision ID: b6f3c2d1e8a9
Revises: a2d9e4f6b7c8
Create Date: 2026-05-29 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b6f3c2d1e8a9"
down_revision: Union[str, None] = "a2d9e4f6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on

    op.create_table(
        "lecture_slide_caption_stored_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("content_length", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    with op.batch_alter_table("lecture_slide_decks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "caption_stored_object_id",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "lecture_slide_chat_available",
                sa.Boolean(),
                server_default="false",
                nullable=False,
            )
        )
        batch_op.create_foreign_key(
            "fk_ls_decks_caption_stored_object_id",
            "lecture_slide_caption_stored_objects",
            ["caption_stored_object_id"],
            ["id"],
        )
        batch_op.create_index(
            op.f("ix_lecture_slide_decks_caption_stored_object_id"),
            ["caption_stored_object_id"],
            unique=False,
        )


def downgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on

    with op.batch_alter_table("lecture_slide_decks") as batch_op:
        batch_op.drop_index(op.f("ix_lecture_slide_decks_caption_stored_object_id"))
        batch_op.drop_constraint(
            "fk_ls_decks_caption_stored_object_id", type_="foreignkey"
        )
        batch_op.drop_column("lecture_slide_chat_available")
        batch_op.drop_column("caption_stored_object_id")
    op.drop_table("lecture_slide_caption_stored_objects")

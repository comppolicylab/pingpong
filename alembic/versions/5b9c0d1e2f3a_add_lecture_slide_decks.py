"""Add lecture slide deck tables

Revision ID: 5b9c0d1e2f3a
Revises: 337b7d1fe811
Create Date: 2026-05-29 14:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5b9c0d1e2f3a"
down_revision: Union[str, None] = "337b7d1fe811"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


lecture_slide_deck_status = sa.Enum(
    "UPLOADED", "PROCESSING", "READY", "FAILED", name="lectureslidedeckstatus"
)
lecture_slide_narration_status = sa.Enum(
    "PENDING",
    "PROCESSING",
    "READY",
    "FAILED",
    name="lectureslidenarrationstatus",
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.create_table(
        "lecture_slide_source_stored_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
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

    op.create_table(
        "lecture_slide_image_stored_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("content_length", sa.Integer(), server_default="0", nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False),
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

    op.create_table(
        "lecture_slide_narration_stored_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("content_length", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
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

    op.create_table(
        "lecture_slide_decks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("source_stored_object_id", sa.Integer(), nullable=False),
        sa.Column("continuous_narration_stored_object_id", sa.Integer(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("voice_id", sa.String(), nullable=True),
        sa.Column("generation_prompt", sa.Text(), nullable=True),
        sa.Column("transcript_data", sa.JSON(), nullable=True),
        sa.Column("context_data", sa.JSON(), nullable=True),
        sa.Column("context_version", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            lecture_slide_deck_status,
            server_default="UPLOADED",
            nullable=False,
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("uploader_id", sa.Integer(), nullable=True),
        sa.Column("source_lecture_slide_deck_id_snapshot", sa.Integer(), nullable=True),
        sa.Column("slide_count", sa.Integer(), nullable=False),
        sa.Column("total_duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"]),
        sa.ForeignKeyConstraint(
            ["continuous_narration_stored_object_id"],
            ["lecture_slide_narration_stored_objects.id"],
            name="fk_ls_decks_continuous_narration_stored_object_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_stored_object_id"],
            ["lecture_slide_source_stored_objects.id"],
            name="fk_ls_decks_source_stored_object_id",
        ),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_lecture_slide_decks_class_id"),
        "lecture_slide_decks",
        ["class_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lecture_slide_decks_continuous_narration_stored_object_id"),
        "lecture_slide_decks",
        ["continuous_narration_stored_object_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lecture_slide_decks_source_stored_object_id"),
        "lecture_slide_decks",
        ["source_stored_object_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lecture_slide_decks_uploader_id"),
        "lecture_slide_decks",
        ["uploader_id"],
        unique=False,
    )

    op.create_table(
        "lecture_slide_narrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stored_object_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            lecture_slide_narration_status,
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["stored_object_id"],
            ["lecture_slide_narration_stored_objects.id"],
            name="fk_ls_narrations_stored_object_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_lecture_slide_narrations_stored_object_id"),
        "lecture_slide_narrations",
        ["stored_object_id"],
        unique=False,
    )

    op.create_table(
        "lecture_slide_pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecture_slide_deck_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("image_stored_object_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("user_notes", sa.Text(), nullable=True),
        sa.Column("narration_text", sa.Text(), nullable=True),
        sa.Column("image_description", sa.Text(), nullable=True),
        sa.Column("narration_id", sa.Integer(), nullable=True),
        sa.Column("start_offset_ms", sa.Integer(), nullable=True),
        sa.Column("end_offset_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["image_stored_object_id"],
            ["lecture_slide_image_stored_objects.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lecture_slide_deck_id"],
            ["lecture_slide_decks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["narration_id"],
            ["lecture_slide_narrations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("narration_id"),
    )
    op.create_index(
        "lecture_slide_page_position_idx",
        "lecture_slide_pages",
        ["lecture_slide_deck_id", "position"],
        unique=True,
    )
    op.create_index(
        op.f("ix_lecture_slide_pages_image_stored_object_id"),
        "lecture_slide_pages",
        ["image_stored_object_id"],
        unique=False,
    )

    op.create_table(
        "lecture_slide_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecture_slide_deck_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("slide_position", sa.Integer(), nullable=False),
        sa.Column("slide_offset_ms", sa.Integer(), nullable=False),
        sa.Column("stop_offset_ms", sa.Integer(), nullable=False),
        sa.Column("question_type", sa.String(), nullable=False),
        sa.Column("question_text", sa.String(), nullable=False),
        sa.Column("intro_text", sa.String(), nullable=False),
        sa.Column("intro_narration_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["intro_narration_id"],
            ["lecture_slide_narrations.id"],
            name="fk_ls_questions_intro_narration_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lecture_slide_deck_id"],
            ["lecture_slide_decks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("intro_narration_id"),
    )
    op.create_index(
        "lecture_slide_question_position_idx",
        "lecture_slide_questions",
        ["lecture_slide_deck_id", "position"],
        unique=True,
    )

    op.create_table(
        "lecture_slide_question_options",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("option_text", sa.String(), nullable=False),
        sa.Column("post_answer_text", sa.String(), nullable=False),
        sa.Column("continue_slide_position", sa.Integer(), nullable=True),
        sa.Column("continue_slide_offset_ms", sa.Integer(), nullable=True),
        sa.Column("continue_offset_ms", sa.Integer(), nullable=False),
        sa.Column("post_narration_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["post_narration_id"],
            ["lecture_slide_narrations.id"],
            name="fk_ls_question_options_post_narration_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["lecture_slide_questions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("post_narration_id"),
        sa.UniqueConstraint("question_id", "id"),
    )
    op.create_index(
        "lecture_slide_question_option_position_idx",
        "lecture_slide_question_options",
        ["question_id", "position"],
        unique=True,
    )

    op.create_table(
        "lecture_slide_question_single_select_correct_options",
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("option_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["lecture_slide_questions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_id", "option_id"],
            [
                "lecture_slide_question_options.question_id",
                "lecture_slide_question_options.id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("question_id"),
    )

    with op.batch_alter_table("assistants") as batch_op:
        batch_op.add_column(sa.Column("lecture_slide_deck_id", sa.Integer()))
        batch_op.create_foreign_key(
            "fk_assistants_lecture_slide_deck_id_lecture_slide_deck",
            "lecture_slide_decks",
            ["lecture_slide_deck_id"],
            ["id"],
        )
        batch_op.create_unique_constraint(
            "uq_assistants_lecture_slide_deck_id", ["lecture_slide_deck_id"]
        )

    with op.batch_alter_table("threads") as batch_op:
        batch_op.add_column(sa.Column("lecture_slide_deck_id", sa.Integer()))
        batch_op.create_foreign_key(
            "fk_threads_lecture_slide_deck_id_lecture_slide_deck",
            "lecture_slide_decks",
            ["lecture_slide_deck_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("threads") as batch_op:
        batch_op.drop_constraint(
            "fk_threads_lecture_slide_deck_id_lecture_slide_deck",
            type_="foreignkey",
        )
        batch_op.drop_column("lecture_slide_deck_id")

    with op.batch_alter_table("assistants") as batch_op:
        batch_op.drop_constraint(
            "uq_assistants_lecture_slide_deck_id",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_assistants_lecture_slide_deck_id_lecture_slide_deck",
            type_="foreignkey",
        )
        batch_op.drop_column("lecture_slide_deck_id")

    op.drop_table("lecture_slide_question_single_select_correct_options")

    op.drop_index(
        "lecture_slide_question_option_position_idx",
        table_name="lecture_slide_question_options",
    )
    op.drop_table("lecture_slide_question_options")

    op.drop_index(
        "lecture_slide_question_position_idx",
        table_name="lecture_slide_questions",
    )
    op.drop_table("lecture_slide_questions")

    op.drop_index(
        op.f("ix_lecture_slide_pages_image_stored_object_id"),
        table_name="lecture_slide_pages",
    )
    op.drop_index(
        "lecture_slide_page_position_idx",
        table_name="lecture_slide_pages",
    )
    op.drop_table("lecture_slide_pages")

    op.drop_index(
        op.f("ix_lecture_slide_narrations_stored_object_id"),
        table_name="lecture_slide_narrations",
    )
    op.drop_index(
        op.f("ix_lecture_slide_decks_uploader_id"),
        table_name="lecture_slide_decks",
    )
    op.drop_index(
        op.f("ix_lecture_slide_decks_source_stored_object_id"),
        table_name="lecture_slide_decks",
    )
    op.drop_index(
        op.f("ix_lecture_slide_decks_continuous_narration_stored_object_id"),
        table_name="lecture_slide_decks",
    )
    op.drop_index(
        op.f("ix_lecture_slide_decks_class_id"),
        table_name="lecture_slide_decks",
    )
    op.drop_table("lecture_slide_narrations")
    op.drop_table("lecture_slide_decks")
    op.drop_table("lecture_slide_narration_stored_objects")
    op.drop_table("lecture_slide_image_stored_objects")
    op.drop_table("lecture_slide_source_stored_objects")

    lecture_slide_narration_status.drop(op.get_bind(), checkfirst=True)
    lecture_slide_deck_status.drop(op.get_bind(), checkfirst=True)

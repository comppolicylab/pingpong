"""add lecture slide translations

Revision ID: e5f7a9b1c3d5
Revises: d4e6f8a0b2c4
Create Date: 2026-08-02 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "e5f7a9b1c3d5"
down_revision: Union[str, None] = "d4e6f8a0b2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


translation_status = sa.Enum(
    "QUEUED",
    "PROCESSING",
    "READY",
    "FAILED",
    name="lectureslidetranslationstatus",
)
translation_status_column = translation_status.with_variant(
    postgresql.ENUM(
        "QUEUED",
        "PROCESSING",
        "READY",
        "FAILED",
        name="lectureslidetranslationstatus",
        create_type=False,
    ),
    "postgresql",
)
translation_stage = sa.Enum(
    "TRANSLATION_TEXT",
    "NARRATION_AUDIO",
    "COMPOSITE_ARTIFACTS",
    name="lectureslidetranslationstage",
)
translation_stage_column = translation_stage.with_variant(
    postgresql.ENUM(
        "TRANSLATION_TEXT",
        "NARRATION_AUDIO",
        "COMPOSITE_ARTIFACTS",
        name="lectureslidetranslationstage",
        create_type=False,
    ),
    "postgresql",
)
translation_run_status = sa.Enum(
    "QUEUED",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    name="lectureslidetranslationrunstatus",
)
translation_run_status_column = translation_run_status.with_variant(
    postgresql.ENUM(
        "QUEUED",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        name="lectureslidetranslationrunstatus",
        create_type=False,
    ),
    "postgresql",
)


def upgrade() -> None:
    translation_status.create(op.get_bind(), checkfirst=True)
    translation_stage.create(op.get_bind(), checkfirst=True)
    translation_run_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "lecture_slide_translations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecture_slide_deck_id", sa.Integer(), nullable=False),
        sa.Column("language_code", sa.String(length=16), nullable=False),
        sa.Column("language_name", sa.String(length=128), nullable=False),
        sa.Column("openai_model", sa.String(), nullable=False),
        sa.Column(
            "status",
            translation_status_column,
            server_default="QUEUED",
            nullable=False,
        ),
        sa.Column(
            "stage",
            translation_stage_column,
            server_default="TRANSLATION_TEXT",
            nullable=False,
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("total_duration_ms", sa.Integer(), nullable=True),
        sa.Column("continuous_narration_stored_object_id", sa.Integer(), nullable=True),
        sa.Column("caption_stored_object_id", sa.Integer(), nullable=True),
        sa.Column(
            "created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["lecture_slide_deck_id"],
            ["lecture_slide_decks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["continuous_narration_stored_object_id"],
            ["lecture_slide_narration_stored_objects.id"],
            name="fk_ls_translations_continuous_narration",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["caption_stored_object_id"],
            ["lecture_slide_caption_stored_objects.id"],
            name="fk_ls_translations_caption",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lecture_slide_deck_id",
            "language_code",
            name="uq_ls_translation_deck_language",
        ),
    )
    op.create_index(
        "ix_ls_translation_continuous_audio",
        "lecture_slide_translations",
        ["continuous_narration_stored_object_id"],
    )
    op.create_index(
        "ix_lecture_slide_translations_caption_stored_object_id",
        "lecture_slide_translations",
        ["caption_stored_object_id"],
    )

    op.create_table(
        "lecture_slide_translation_pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("translation_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("narration_text", sa.Text(), nullable=True),
        sa.Column("narration_stored_object_id", sa.Integer(), nullable=True),
        sa.Column("word_timings", sa.JSON(), nullable=True),
        sa.Column("start_offset_ms", sa.Integer(), nullable=True),
        sa.Column("end_offset_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["translation_id"],
            ["lecture_slide_translations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["narration_stored_object_id"],
            ["lecture_slide_narration_stored_objects.id"],
            name="fk_ls_translation_pages_narration",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "translation_id",
            "position",
            name="uq_ls_translation_page_position",
        ),
    )
    op.create_index(
        "ix_ls_translation_page_audio",
        "lecture_slide_translation_pages",
        ["narration_stored_object_id"],
    )

    op.create_table(
        "lecture_slide_translation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("translation_id", sa.Integer(), nullable=True),
        sa.Column("translation_id_snapshot", sa.Integer(), nullable=False),
        sa.Column("stage", translation_stage_column, nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("completed_parts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_parts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status",
            translation_run_status_column,
            server_default="QUEUED",
            nullable=False,
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("lease_token", sa.String(), nullable=True),
        sa.Column("leased_by", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["translation_id"],
            ["lecture_slide_translations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "translation_id_snapshot",
            "attempt_number",
            name="uq_ls_translation_run_attempt",
        ),
    )
    op.create_index(
        "ix_lecture_slide_translation_runs_translation_id",
        "lecture_slide_translation_runs",
        ["translation_id"],
    )
    op.create_index(
        "ix_ls_translation_run_snapshot",
        "lecture_slide_translation_runs",
        ["translation_id_snapshot"],
    )
    op.create_index(
        "ix_lecture_slide_translation_runs_updated",
        "lecture_slide_translation_runs",
        ["updated"],
    )
    op.create_index(
        "lecture_slide_translation_runs_active_idx",
        "lecture_slide_translation_runs",
        ["translation_id_snapshot"],
        unique=True,
        sqlite_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
        postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
    )
    op.create_index(
        "lecture_slide_translation_runs_status_lease_idx",
        "lecture_slide_translation_runs",
        ["status", "lease_expires_at"],
    )

    with op.batch_alter_table("threads") as batch_op:
        batch_op.add_column(
            sa.Column("lecture_slide_translation_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("lecture_language_code", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(
            sa.Column("lecture_language_name", sa.String(length=128), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_threads_lecture_slide_translation_id",
            "lecture_slide_translations",
            ["lecture_slide_translation_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_threads_lecture_slide_translation_id",
            ["lecture_slide_translation_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("threads") as batch_op:
        batch_op.drop_index("ix_threads_lecture_slide_translation_id")
        batch_op.drop_constraint(
            "fk_threads_lecture_slide_translation_id", type_="foreignkey"
        )
        batch_op.drop_column("lecture_language_name")
        batch_op.drop_column("lecture_language_code")
        batch_op.drop_column("lecture_slide_translation_id")

    op.drop_table("lecture_slide_translation_runs")
    op.drop_table("lecture_slide_translation_pages")
    op.drop_table("lecture_slide_translations")

    translation_run_status.drop(op.get_bind(), checkfirst=True)
    translation_stage.drop(op.get_bind(), checkfirst=True)
    translation_status.drop(op.get_bind(), checkfirst=True)

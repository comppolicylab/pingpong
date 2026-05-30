"""Add lecture slide processing runs

Revision ID: c2f4e8a9d3b1
Revises: b6f3c2d1e8a9
Create Date: 2026-05-29 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2f4e8a9d3b1"
down_revision: Union[str, None] = "b6f3c2d1e8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on

    with op.batch_alter_table("lecture_slide_decks") as batch_op:
        batch_op.add_column(sa.Column("narration_prompt", sa.Text(), nullable=True))

    with op.batch_alter_table("lecture_slide_pages") as batch_op:
        batch_op.add_column(
            sa.Column("narration_stored_object_id", sa.Integer(), nullable=True)
        )
        batch_op.create_index(
            "ix_lecture_slide_pages_narration_stored_object_id",
            ["narration_stored_object_id"],
        )
        batch_op.create_foreign_key(
            "fk_ls_pages_narration_stored_object_id",
            "lecture_slide_narration_stored_objects",
            ["narration_stored_object_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "lecture_slide_processing_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecture_slide_deck_id", sa.Integer(), nullable=True),
        sa.Column("lecture_slide_deck_id_snapshot", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("assistant_id_at_start", sa.Integer(), nullable=True),
        sa.Column(
            "stage",
            sa.Enum(
                "SLIDE_ASSET_EXTRACTION",
                "NARRATION_TEXT",
                "NARRATION_AUDIO",
                "NARRATION_TRANSCRIPTION",
                "MANIFEST_GENERATION",
                "COMPOSITE_ARTIFACTS",
                name="lectureslideprocessingstage",
            ),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                name="lectureslideprocessingrunstatus",
            ),
            server_default="QUEUED",
            nullable=False,
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column(
            "cancel_reason",
            sa.Enum(
                "ASSISTANT_DETACHED",
                "ASSISTANT_DELETED",
                "LECTURE_SLIDE_DECK_DELETED",
                name="lectureslideprocessingcancelreason",
            ),
            nullable=True,
        ),
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
            ["lecture_slide_deck_id"],
            ["lecture_slide_decks.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lecture_slide_processing_runs_class_id",
        "lecture_slide_processing_runs",
        ["class_id"],
    )
    op.create_index(
        "ix_lecture_slide_processing_runs_lecture_slide_deck_id",
        "lecture_slide_processing_runs",
        ["lecture_slide_deck_id"],
    )
    op.create_index(
        "ix_lecture_slide_processing_runs_lecture_slide_deck_id_snapshot",
        "lecture_slide_processing_runs",
        ["lecture_slide_deck_id_snapshot"],
    )
    op.create_index(
        "ix_lecture_slide_processing_runs_updated",
        "lecture_slide_processing_runs",
        ["updated"],
    )
    op.create_index(
        "lecture_slide_processing_runs_active_idx",
        "lecture_slide_processing_runs",
        ["lecture_slide_deck_id_snapshot"],
        unique=True,
        sqlite_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
        postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
    )
    op.create_index(
        "lecture_slide_processing_runs_status_stage_lease_idx",
        "lecture_slide_processing_runs",
        ["status", "stage", "lease_expires_at"],
    )
    op.create_index(
        "lecture_slide_processing_runs_snapshot_attempt_idx",
        "lecture_slide_processing_runs",
        ["lecture_slide_deck_id_snapshot", "attempt_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "lecture_slide_processing_runs_snapshot_attempt_idx",
        table_name="lecture_slide_processing_runs",
    )
    op.drop_index(
        "lecture_slide_processing_runs_status_stage_lease_idx",
        table_name="lecture_slide_processing_runs",
    )
    op.drop_index(
        "lecture_slide_processing_runs_active_idx",
        table_name="lecture_slide_processing_runs",
    )
    op.drop_index(
        "ix_lecture_slide_processing_runs_updated",
        table_name="lecture_slide_processing_runs",
    )
    op.drop_index(
        "ix_lecture_slide_processing_runs_lecture_slide_deck_id_snapshot",
        table_name="lecture_slide_processing_runs",
    )
    op.drop_index(
        "ix_lecture_slide_processing_runs_lecture_slide_deck_id",
        table_name="lecture_slide_processing_runs",
    )
    op.drop_index(
        "ix_lecture_slide_processing_runs_class_id",
        table_name="lecture_slide_processing_runs",
    )
    op.drop_table("lecture_slide_processing_runs")

    with op.batch_alter_table("lecture_slide_pages") as batch_op:
        batch_op.drop_constraint(
            "fk_ls_pages_narration_stored_object_id",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_lecture_slide_pages_narration_stored_object_id")
        batch_op.drop_column("narration_stored_object_id")

    with op.batch_alter_table("lecture_slide_decks") as batch_op:
        batch_op.drop_column("narration_prompt")

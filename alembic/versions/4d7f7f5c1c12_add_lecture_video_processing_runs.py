"""Add lecture video processing runs

Revision ID: 4d7f7f5c1c12
Revises: 1dc0c8626e4a
Create Date: 2026-03-16 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4d7f7f5c1c12"
down_revision: Union[str, None] = "1dc0c8626e4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


lecture_video_processing_stage = sa.Enum(
    "NARRATION",
    name="lecturevideoprocessingstage",
)
lecture_video_processing_run_status = sa.Enum(
    "QUEUED",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    name="lecturevideoprocessingrunstatus",
)
lecture_video_processing_cancel_reason = sa.Enum(
    "ASSISTANT_DETACHED",
    "ASSISTANT_DELETED",
    "LECTURE_VIDEO_DELETED",
    name="lecturevideoprocessingcancelreason",
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.add_column(
        "lecture_videos",
        sa.Column("source_lecture_video_id_snapshot", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_lecture_videos_source_lecture_video_id_snapshot"),
        "lecture_videos",
        ["source_lecture_video_id_snapshot"],
        unique=False,
    )

    op.create_table(
        "lecture_video_processing_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecture_video_id", sa.Integer(), nullable=True),
        sa.Column("lecture_video_id_snapshot", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("assistant_id_at_start", sa.Integer(), nullable=True),
        sa.Column("stage", lecture_video_processing_stage, nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            lecture_video_processing_run_status,
            nullable=False,
            server_default="QUEUED",
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column(
            "cancel_reason",
            lecture_video_processing_cancel_reason,
            nullable=True,
        ),
        sa.Column("lease_token", sa.String(), nullable=True),
        sa.Column("leased_by", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["lecture_video_id"], ["lecture_videos.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_lecture_video_processing_runs_class_id"),
        "lecture_video_processing_runs",
        ["class_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lecture_video_processing_runs_lecture_video_id"),
        "lecture_video_processing_runs",
        ["lecture_video_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lecture_video_processing_runs_lecture_video_id_snapshot"),
        "lecture_video_processing_runs",
        ["lecture_video_id_snapshot"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lecture_video_processing_runs_updated"),
        "lecture_video_processing_runs",
        ["updated"],
        unique=False,
    )
    op.create_index(
        "lecture_video_processing_runs_active_stage_idx",
        "lecture_video_processing_runs",
        ["lecture_video_id_snapshot", "stage"],
        unique=True,
        sqlite_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
        postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
    )
    op.create_index(
        "lecture_video_processing_runs_status_stage_lease_idx",
        "lecture_video_processing_runs",
        ["status", "stage", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "lecture_video_processing_runs_snapshot_stage_attempt_idx",
        "lecture_video_processing_runs",
        ["lecture_video_id_snapshot", "stage", "attempt_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_lecture_videos_source_lecture_video_id_snapshot"),
        table_name="lecture_videos",
    )
    op.drop_column("lecture_videos", "source_lecture_video_id_snapshot")

    op.drop_index(
        "lecture_video_processing_runs_snapshot_stage_attempt_idx",
        table_name="lecture_video_processing_runs",
    )
    op.drop_index(
        "lecture_video_processing_runs_status_stage_lease_idx",
        table_name="lecture_video_processing_runs",
    )
    op.drop_index(
        "lecture_video_processing_runs_active_stage_idx",
        table_name="lecture_video_processing_runs",
    )
    op.drop_index(
        op.f("ix_lecture_video_processing_runs_updated"),
        table_name="lecture_video_processing_runs",
    )
    op.drop_index(
        op.f("ix_lecture_video_processing_runs_lecture_video_id_snapshot"),
        table_name="lecture_video_processing_runs",
    )
    op.drop_index(
        op.f("ix_lecture_video_processing_runs_lecture_video_id"),
        table_name="lecture_video_processing_runs",
    )
    op.drop_index(
        op.f("ix_lecture_video_processing_runs_class_id"),
        table_name="lecture_video_processing_runs",
    )
    op.drop_table("lecture_video_processing_runs")

    bind = op.get_bind()
    lecture_video_processing_cancel_reason.drop(bind, checkfirst=True)
    lecture_video_processing_run_status.drop(bind, checkfirst=True)
    lecture_video_processing_stage.drop(bind, checkfirst=True)

"""add run release and moderation checks

Revision ID: 9d7e2a6c4b81
Revises: 279ffe054fcd
Create Date: 2026-10-27

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d7e2a6c4b81"
down_revision: Union[str, None] = "279ffe054fcd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


release_type = sa.Enum(
    "IMMEDIATE",
    "AFTER_INPUT_MODERATION",
    "AFTER_INPUT_AND_OUTPUT_MODERATION",
    name="threadreleasetype",
)
release_status = sa.Enum("PENDING", "RELEASED", "WITHHELD", name="runreleasestatus")
check_stage = sa.Enum("INPUT", "OUTPUT", name="moderationcheckstage")
check_status = sa.Enum(
    "PENDING", "PASSED", "FLAGGED", "ERRORED", "CANCELLED", name="moderationcheckstatus"
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on
    # ADD COLUMN does not create PostgreSQL enum types automatically.
    release_type.create(op.get_bind(), checkfirst=True)
    release_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "threads",
        sa.Column(
            "release_type", release_type, server_default="IMMEDIATE", nullable=False
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "release_type", release_type, server_default="IMMEDIATE", nullable=False
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "release_status", release_status, server_default="RELEASED", nullable=False
        ),
    )
    # Historical release times are unknown; preserve NULL rather than inventing them.
    op.add_column(
        "runs", sa.Column("released_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "run_moderation_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", check_stage, nullable=False),
        sa.Column("status", check_status, server_default="PENDING", nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("source_items", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_run_moderation_checks_run_id", "run_moderation_checks", ["run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_run_moderation_checks_run_id", table_name="run_moderation_checks")
    op.drop_table("run_moderation_checks")
    check_status.drop(op.get_bind(), checkfirst=True)
    check_stage.drop(op.get_bind(), checkfirst=True)
    op.drop_column("runs", "released_at")
    op.drop_column("runs", "release_status")
    op.drop_column("runs", "release_type")
    op.drop_column("threads", "release_type")
    release_status.drop(op.get_bind(), checkfirst=True)
    release_type.drop(op.get_bind(), checkfirst=True)

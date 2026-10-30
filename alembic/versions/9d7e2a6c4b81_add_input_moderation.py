"""add input moderation

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


check_status = sa.Enum(
    "PENDING", "PASSED", "FLAGGED", "ERRORED", "CANCELLED", name="moderationcheckstatus"
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on
    for table in ("assistants", "threads", "runs"):
        op.add_column(
            table,
            sa.Column(
                "input_moderation_enabled",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
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
        sa.Column("status", check_status, server_default="PENDING", nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("message_ids", sa.JSON(), server_default="[]", nullable=False),
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
    op.drop_column("runs", "input_moderation_enabled")
    op.drop_column("threads", "input_moderation_enabled")
    op.drop_column("assistants", "input_moderation_enabled")

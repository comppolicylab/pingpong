"""Index run threads without holding schema-change locks during the build.

Revision ID: e8a21f4d6c90
Revises: 9d7e2a6c4b81
Create Date: 2026-10-30

"""

from alembic import op


revision = "e8a21f4d6c90"
down_revision = "9d7e2a6c4b81"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            # A cancelled concurrent build can leave an invalid index behind.
            # This revision owns the index, so remove it before retrying a build.
            op.drop_index(
                "ix_runs_thread_id",
                table_name="runs",
                if_exists=True,
                postgresql_concurrently=True,
            )
            op.create_index(
                "ix_runs_thread_id",
                "runs",
                ["thread_id"],
                postgresql_concurrently=True,
            )
    else:
        op.create_index("ix_runs_thread_id", "runs", ["thread_id"])


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index(
                "ix_runs_thread_id", table_name="runs", postgresql_concurrently=True
            )
    else:
        op.drop_index("ix_runs_thread_id", table_name="runs")

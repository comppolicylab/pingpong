"""Let anonymous sessions own lecture lesson controller leases.

Revision ID: 5d8e2b7c1a40
Revises: 3c7d1e9a5b20
"""

from alembic import op
import sqlalchemy as sa

revision = "5d8e2b7c1a40"
down_revision = "3c7d1e9a5b20"
branch_labels = None
depends_on = None

TABLES = ("lecture_slide_thread_states", "lecture_video_thread_states")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("controller_anonymous_session_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{table}_controller_anonymous_session_id",
            table,
            "anonymous_sessions",
            ["controller_anonymous_session_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_constraint(
            f"fk_{table}_controller_anonymous_session_id", table, type_="foreignkey"
        )
        op.drop_column(table, "controller_anonymous_session_id")

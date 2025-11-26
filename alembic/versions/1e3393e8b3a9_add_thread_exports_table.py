"""Add thread exports table

Revision ID: 1e3393e8b3a9
Revises: 90e1564bb31d
Create Date: 2025-02-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "1e3393e8b3a9"
down_revision: str | None = "90e1564bb31d"
branch_labels: str | None = None
depends_on: str | None = None


export_status = sa.Enum(
    "pending",
    "processing",
    "ready",
    "failed",
    "expired",
    name="threadexportstatus",
)


def upgrade() -> None:
    bind = op.get_bind()
    export_status.create(bind, checkfirst=True)

    op.create_table(
        "thread_exports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            export_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "s3_file_id",
            sa.Integer(),
            sa.ForeignKey("s3_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_thread_exports_thread_id", "thread_exports", ["thread_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_thread_exports_thread_id", table_name="thread_exports")
    op.drop_table("thread_exports")
    bind = op.get_bind()
    export_status.drop(bind, checkfirst=True)

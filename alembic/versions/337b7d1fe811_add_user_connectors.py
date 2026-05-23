"""Add user_connectors table

Revision ID: 337b7d1fe811
Revises: 7e6f23c1a9b4
Create Date: 2026-04-18 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "337b7d1fe811"
down_revision: Union[str, None] = "7e6f23c1a9b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.create_table(
        "user_connectors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("service", sa.String(), nullable=False),
        sa.Column("account_scope", sa.String(), nullable=True),
        sa.Column("access_token", sa.String(), nullable=False),
        sa.Column("refresh_token", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.String(), nullable=True),
        sa.Column("external_user_id", sa.String(), nullable=True),
        sa.Column("external_identity", sa.JSON(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        # NB: no ondelete="CASCADE" — user deletion must revoke through the
        # connector before dropping rows, otherwise the upstream tokens stay
        # valid on the provider side.
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_user_connectors_user_id",
        "user_connectors",
        ["user_id"],
    )
    # Partial indexes instead of plain UniqueConstraints so NULL account
    # scopes and optional provider identities dedupe consistently across
    # PostgreSQL and SQLite. Identity-aware connectors may store multiple
    # rows for the same (user, service, account_scope) as long as each row
    # has a distinct external_user_id. Connectors that cannot resolve a
    # stable provider identity keep the previous one-row-per-scope behavior.
    op.create_index(
        "uq_user_connector_no_scope_no_identity",
        "user_connectors",
        ["user_id", "service"],
        unique=True,
        postgresql_where=sa.text("account_scope IS NULL AND external_user_id IS NULL"),
        sqlite_where=sa.text("account_scope IS NULL AND external_user_id IS NULL"),
    )
    op.create_index(
        "uq_user_connector_scope_no_identity",
        "user_connectors",
        ["user_id", "service", "account_scope"],
        unique=True,
        postgresql_where=sa.text(
            "account_scope IS NOT NULL AND external_user_id IS NULL"
        ),
        sqlite_where=sa.text("account_scope IS NOT NULL AND external_user_id IS NULL"),
    )
    op.create_index(
        "uq_user_connector_no_scope_identity",
        "user_connectors",
        ["user_id", "service", "external_user_id"],
        unique=True,
        postgresql_where=sa.text(
            "account_scope IS NULL AND external_user_id IS NOT NULL"
        ),
        sqlite_where=sa.text("account_scope IS NULL AND external_user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_user_connector_scope_identity",
        "user_connectors",
        ["user_id", "service", "account_scope", "external_user_id"],
        unique=True,
        postgresql_where=sa.text(
            "account_scope IS NOT NULL AND external_user_id IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "account_scope IS NOT NULL AND external_user_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_user_connector_scope_identity", table_name="user_connectors")
    op.drop_index("uq_user_connector_no_scope_identity", table_name="user_connectors")
    op.drop_index("uq_user_connector_scope_no_identity", table_name="user_connectors")
    op.drop_index(
        "uq_user_connector_no_scope_no_identity", table_name="user_connectors"
    )
    op.drop_index("idx_user_connectors_user_id", table_name="user_connectors")
    op.drop_table("user_connectors")

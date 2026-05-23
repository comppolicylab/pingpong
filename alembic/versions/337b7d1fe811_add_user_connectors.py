"""Add connector config and user connector tables

Revision ID: 337b7d1fe811
Revises: 9a0d4b5c7e8f
Create Date: 2026-04-18 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "337b7d1fe811"
down_revision: Union[str, None] = "9a0d4b5c7e8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.create_table(
        "connector_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service", sa.String(), nullable=False),
        sa.Column("account_scope", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("client_secret", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_connector_configs_service_account_scope",
        "connector_configs",
        ["service", "account_scope"],
        unique=True,
    )

    op.create_table(
        "user_connectors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("connector_config_id", sa.Integer(), nullable=False),
        sa.Column("service", sa.String(), nullable=False),
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
        sa.ForeignKeyConstraint(["connector_config_id"], ["connector_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_user_connectors_user_id",
        "user_connectors",
        ["user_id"],
    )
    op.create_index(
        "idx_user_connectors_connector_config_id",
        "user_connectors",
        ["connector_config_id"],
    )
    # Identity-aware connectors may store multiple rows for the same
    # (user, connector_config) as long as each row has a distinct
    # external_user_id. Connectors that cannot resolve a stable provider
    # identity keep the one-row-per-config behavior.
    op.create_index(
        "uq_user_connector_config_no_identity",
        "user_connectors",
        ["user_id", "connector_config_id"],
        unique=True,
        postgresql_where=sa.text("external_user_id IS NULL"),
        sqlite_where=sa.text("external_user_id IS NULL"),
    )
    op.create_index(
        "uq_user_connector_config_identity",
        "user_connectors",
        ["user_id", "connector_config_id", "external_user_id"],
        unique=True,
        postgresql_where=sa.text("external_user_id IS NOT NULL"),
        sqlite_where=sa.text("external_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_connector_config_identity", table_name="user_connectors")
    op.drop_index("uq_user_connector_config_no_identity", table_name="user_connectors")
    op.drop_index(
        "idx_user_connectors_connector_config_id", table_name="user_connectors"
    )
    op.drop_index("idx_user_connectors_user_id", table_name="user_connectors")
    op.drop_table("user_connectors")
    op.drop_index(
        "uq_connector_configs_service_account_scope", table_name="connector_configs"
    )
    op.drop_table("connector_configs")

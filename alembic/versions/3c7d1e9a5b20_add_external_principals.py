"""Add external principals for Open Access.

Revision ID: 3c7d1e9a5b20
Revises: 8e2f4a6c9d10
"""

from alembic import op
import sqlalchemy as sa

revision = "3c7d1e9a5b20"
down_revision = "8e2f4a6c9d10"
branch_labels = None
depends_on = None

external_principal_tier_enum = sa.Enum(
    "ANONYMOUS", "REGISTERED", name="externalprincipaltier"
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.create_table(
        "external_principals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("tier", external_principal_tier_enum, nullable=False),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "client_id", "subject", name="uq_external_principals_client_subject"
        ),
    )
    op.add_column(
        "anonymous_sessions",
        sa.Column("external_principal_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_anonymous_sessions_external_principal_id",
        "anonymous_sessions",
        "external_principals",
        ["external_principal_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_anonymous_sessions_external_principal_id",
        "anonymous_sessions",
        ["external_principal_id"],
    )
    op.add_column(
        "threads",
        sa.Column("external_principal_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_threads_external_principal_id",
        "threads",
        "external_principals",
        ["external_principal_id"],
        ["id"],
    )
    op.create_index(
        "threads_external_principal_assistant_idx",
        "threads",
        ["external_principal_id", "assistant_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("threads_external_principal_assistant_idx", table_name="threads")
    op.drop_constraint(
        "fk_threads_external_principal_id", "threads", type_="foreignkey"
    )
    op.drop_column("threads", "external_principal_id")
    op.drop_index(
        "ix_anonymous_sessions_external_principal_id", table_name="anonymous_sessions"
    )
    op.drop_constraint(
        "fk_anonymous_sessions_external_principal_id",
        "anonymous_sessions",
        type_="foreignkey",
    )
    op.drop_column("anonymous_sessions", "external_principal_id")
    op.drop_table("external_principals")
    external_principal_tier_enum.drop(op.get_bind(), checkfirst=True)

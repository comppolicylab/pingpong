"""Add Panopto integration fields and internal MCP tool support

Revision ID: 4209ab7d4b7b
Revises: 4d7f7f5c1c12
Create Date: 2026-03-18 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4209ab7d4b7b"
down_revision: Union[str, None] = "4d7f7f5c1c12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    panopto_status_enum = sa.Enum(
        "NONE",
        "AUTHORIZED",
        "LINKED",
        "ERROR",
        "DISMISSED",
        name="panoptostatus",
    )
    panopto_status_enum.create(op.get_bind(), checkfirst=True)

    # Panopto fields on classes
    op.add_column(
        "classes",
        sa.Column(
            "panopto_status", panopto_status_enum, nullable=True, server_default="NONE"
        ),
    )
    op.add_column("classes", sa.Column("panopto_tenant", sa.String(), nullable=True))
    op.add_column(
        "classes",
        sa.Column(
            "panopto_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
    )
    op.add_column("classes", sa.Column("panopto_folder_id", sa.String(), nullable=True))
    op.add_column(
        "classes", sa.Column("panopto_folder_name", sa.String(), nullable=True)
    )
    op.add_column(
        "classes", sa.Column("panopto_access_token", sa.String(), nullable=True)
    )
    op.add_column(
        "classes", sa.Column("panopto_refresh_token", sa.String(), nullable=True)
    )
    op.add_column(
        "classes", sa.Column("panopto_expires_in", sa.Integer(), nullable=True)
    )
    op.add_column(
        "classes",
        sa.Column("panopto_token_added_at", sa.DateTime(timezone=True), nullable=True),
    )

    # is_internal flag on mcp_server_tools
    op.add_column(
        "mcp_server_tools",
        sa.Column(
            "is_internal",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )

    # Class-level MCP tool associations
    op.create_table(
        "mcp_server_tool_class_associations",
        sa.Column("mcp_server_tool_id", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mcp_server_tool_id"],
            ["mcp_server_tools.id"],
        ),
    )
    op.create_index(
        "mcp_server_tool_class_idx",
        "mcp_server_tool_class_associations",
        ["mcp_server_tool_id", "class_id"],
        unique=True,
    )


def downgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    # Drop class association table
    op.drop_index(
        "mcp_server_tool_class_idx",
        table_name="mcp_server_tool_class_associations",
    )
    op.drop_table("mcp_server_tool_class_associations")

    # Drop is_internal column
    op.drop_column("mcp_server_tools", "is_internal")

    # Drop Panopto columns
    op.drop_column("classes", "panopto_token_added_at")
    op.drop_column("classes", "panopto_expires_in")
    op.drop_column("classes", "panopto_refresh_token")
    op.drop_column("classes", "panopto_access_token")
    op.drop_column("classes", "panopto_folder_name")
    op.drop_column("classes", "panopto_folder_id")
    op.drop_column("classes", "panopto_user_id")
    op.drop_column("classes", "panopto_tenant")
    op.drop_column("classes", "panopto_status")

    sa.Enum(name="panoptostatus").drop(op.get_bind(), checkfirst=True)

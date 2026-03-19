"""Refactor internal MCP tools: add is_internal, class association table

Revision ID: a7b3c4d5e6f7
Revises: 4209ab7d4b7b
Create Date: 2026-03-19 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7b3c4d5e6f7"
down_revision: Union[str, None] = "4209ab7d4b7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    # 1. Add is_internal column to mcp_server_tools
    op.add_column(
        "mcp_server_tools",
        sa.Column(
            "is_internal",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )

    # 2. Create mcp_server_tool_class_associations table
    op.create_table(
        "mcp_server_tool_class_associations",
        sa.Column("mcp_server_tool_id", sa.Integer(), nullable=True),
        sa.Column("class_id", sa.Integer(), nullable=True),
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

    # 3. Data migration: move existing panopto_mcp_server_tool_id refs
    # into the new association table and mark tools as internal
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, panopto_mcp_server_tool_id FROM classes "
            "WHERE panopto_mcp_server_tool_id IS NOT NULL"
        )
    ).fetchall()

    for class_id, tool_id in rows:
        conn.execute(
            sa.text(
                "INSERT INTO mcp_server_tool_class_associations "
                "(mcp_server_tool_id, class_id) VALUES (:tool_id, :class_id)"
            ),
            {"tool_id": tool_id, "class_id": class_id},
        )
        conn.execute(
            sa.text(
                "UPDATE mcp_server_tools SET is_internal = true, "
                "authorization_token = NULL WHERE id = :tool_id"
            ),
            {"tool_id": tool_id},
        )

    # 4. Drop the panopto_mcp_server_tool_id column from classes
    op.drop_constraint(
        "classes_panopto_mcp_server_tool_id_fkey",
        "classes",
        type_="foreignkey",
    )
    op.drop_column("classes", "panopto_mcp_server_tool_id")


def downgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    # Add back the panopto_mcp_server_tool_id column
    op.add_column(
        "classes",
        sa.Column(
            "panopto_mcp_server_tool_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "classes_panopto_mcp_server_tool_id_fkey",
        "classes",
        "mcp_server_tools",
        ["panopto_mcp_server_tool_id"],
        ["id"],
    )

    # Migrate data back
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT mcp_server_tool_id, class_id "
            "FROM mcp_server_tool_class_associations"
        )
    ).fetchall()
    for tool_id, class_id in rows:
        conn.execute(
            sa.text(
                "UPDATE classes SET panopto_mcp_server_tool_id = :tool_id "
                "WHERE id = :class_id"
            ),
            {"tool_id": tool_id, "class_id": class_id},
        )

    # Drop association table
    op.drop_index(
        "mcp_server_tool_class_idx",
        table_name="mcp_server_tool_class_associations",
    )
    op.drop_table("mcp_server_tool_class_associations")

    # Drop is_internal column
    op.drop_column("mcp_server_tools", "is_internal")

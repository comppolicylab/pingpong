"""add assistant avatar

Revision ID: a1867d4e2f90
Revises: c8f2d4e6a1b3
Create Date: 2026-07-29 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1867d4e2f90"
down_revision: Union[str, None] = "c8f2d4e6a1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    with op.batch_alter_table("assistants") as batch_op:
        batch_op.add_column(sa.Column("avatar_file_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_assistants_avatar_file_id_files",
            "files",
            ["avatar_file_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("assistants") as batch_op:
        batch_op.drop_constraint(
            "fk_assistants_avatar_file_id_files", type_="foreignkey"
        )
        batch_op.drop_column("avatar_file_id")

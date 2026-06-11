"""Add Code Interpreter visibility settings

Revision ID: 3e4f5a6b7c8d
Revises: 7c1d9e2f3a4b
Create Date: 2026-06-10 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3e4f5a6b7c8d"
down_revision: Union[str, None] = "7c1d9e2f3a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column(
        "assistants",
        sa.Column(
            "hide_code_interpreter_code",
            sa.Boolean(),
            server_default="false",
            nullable=True,
        ),
    )
    op.add_column(
        "assistants",
        sa.Column(
            "hide_code_interpreter_output",
            sa.Boolean(),
            server_default="false",
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("assistants", "hide_code_interpreter_output")
    op.drop_column("assistants", "hide_code_interpreter_code")

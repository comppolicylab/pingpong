"""add thread deletion protection

Revision ID: b72f1c3d4e5a
Revises: a1867d4e2f90
Create Date: 2026-07-29 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b72f1c3d4e5a"
down_revision: Union[str, None] = "a1867d4e2f90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column(
        "assistants",
        sa.Column(
            "prevent_user_thread_deletion",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "threads",
        sa.Column(
            "prevent_user_thread_deletion",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("threads", "prevent_user_thread_deletion")
    op.drop_column("assistants", "prevent_user_thread_deletion")

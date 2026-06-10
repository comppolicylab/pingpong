"""Threads: Add is_test column

Revision ID: 3e8a1c5d9b27
Revises: 7c1d9e2f3a4b
Create Date: 2026-06-10 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3e8a1c5d9b27"
down_revision: Union[str, None] = "7c1d9e2f3a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column(
        "threads",
        sa.Column("is_test", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("threads", "is_test")

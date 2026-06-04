"""Add run moderation

Revision ID: 6e1f8c9a4d2b
Revises: c2f4e8a9d3b1
Create Date: 2026-06-04 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6e1f8c9a4d2b"
down_revision: Union[str, None] = "c2f4e8a9d3b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column("runs", sa.Column("moderation", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "moderation")

"""Add message metadata

Revision ID: 9f1a2b3c4d5e
Revises: 3e4f5a6b7c8d
Create Date: 2026-06-12 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f1a2b3c4d5e"
down_revision: Union[str, None] = "3e4f5a6b7c8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column("messages", sa.Column("metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "metadata")

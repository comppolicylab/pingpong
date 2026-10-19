"""Add run usage

Revision ID: 6657eaa22494
Revises: d2f4a6c8e0b1
Create Date: 2026-10-19 11:16:30.121320

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6657eaa22494"
down_revision: Union[str, None] = "d2f4a6c8e0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column("runs", sa.Column("usage", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "usage")

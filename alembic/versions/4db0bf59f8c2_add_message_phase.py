"""Add message phase for v3 assistant messages

Revision ID: 4db0bf59f8c2
Revises: 6812f442bbbb
Create Date: 2026-03-13 12:50:47.123456

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4db0bf59f8c2"
down_revision: Union[str, None] = "6812f442bbbb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column("messages", sa.Column("phase", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "phase")

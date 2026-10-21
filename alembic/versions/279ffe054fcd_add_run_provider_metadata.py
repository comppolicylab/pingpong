"""add run provider metadata

Revision ID: 279ffe054fcd
Revises: 64deb966df69
Create Date: 2026-10-20 20:24:51.689686

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "279ffe054fcd"
down_revision: Union[str, None] = "64deb966df69"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column("runs", sa.Column("provider_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "provider_metadata")

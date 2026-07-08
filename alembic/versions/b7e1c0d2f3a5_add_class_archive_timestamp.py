"""add class archive timestamp

Revision ID: b7e1c0d2f3a5
Revises: b7e1c0d2f3a4
Create Date: 2026-07-08 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b7e1c0d2f3a5"
down_revision: Union[str, None] = "b7e1c0d2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "classes",
        sa.Column("archived", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("classes", "archived")

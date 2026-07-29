"""unbundle assistant markup settings

Revision ID: d4e6f8a0b2c4
Revises: b72f1c3d4e5a
Create Date: 2026-07-29 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4e6f8a0b2c4"
down_revision: Union[str, None] = "b72f1c3d4e5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing assistants predate the independent settings, so preserve all
    # three capabilities for them.
    op.add_column(
        "assistants",
        sa.Column(
            "use_mermaid", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
    )
    op.add_column(
        "assistants",
        sa.Column("use_svg", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.execute(sa.text("UPDATE assistants SET use_latex = true"))


def downgrade() -> None:
    op.drop_column("assistants", "use_svg")
    op.drop_column("assistants", "use_mermaid")

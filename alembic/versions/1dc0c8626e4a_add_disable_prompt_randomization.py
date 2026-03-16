"""Add disable prompt randomization

Revision ID: 1dc0c8626e4a
Revises: 3d0b22f9fd11
Create Date: 2026-03-16 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1dc0c8626e4a"
down_revision: Union[str, None] = "3d0b22f9fd11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.add_column(
        "assistants",
        sa.Column(
            "disable_prompt_randomization",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("assistants", "disable_prompt_randomization")

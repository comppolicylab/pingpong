"""Add lesson timeline bypass assistant policy

Revision ID: 0a1b2c3d4e5f
Revises: 9f1a2b3c4d5e
Create Date: 2026-06-13 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0a1b2c3d4e5f"
down_revision: Union[str, None] = "9f1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column(
        "assistants",
        sa.Column(
            "allow_lesson_timeline_bypass",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("assistants", "allow_lesson_timeline_bypass")

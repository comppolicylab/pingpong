"""scope lecture slide narration generation to inserted pages

Revision ID: 3b62b41855a2
Revises: a7c942e31b08
Create Date: 2026-11-20 02:14:03.772707

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "3b62b41855a2"
down_revision: Union[str, None] = "a7c942e31b08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column(
        "lecture_slide_processing_runs",
        sa.Column("narration_positions", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lecture_slide_processing_runs", "narration_positions")

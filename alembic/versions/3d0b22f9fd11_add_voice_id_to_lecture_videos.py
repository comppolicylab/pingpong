"""Add voice_id to lecture videos

Revision ID: 3d0b22f9fd11
Revises: 86d7206db7f1
Create Date: 2026-03-14 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3d0b22f9fd11"
down_revision: Union[str, None] = "86d7206db7f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.add_column("lecture_videos", sa.Column("voice_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("lecture_videos", "voice_id")

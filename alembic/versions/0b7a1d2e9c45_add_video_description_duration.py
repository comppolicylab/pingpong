"""add video description duration

Revision ID: 0b7a1d2e9c45
Revises: df25d20d0f3a
Create Date: 2026-04-28 00:00:00.000000

"""

from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0b7a1d2e9c45"
down_revision: Union[str, None] = "df25d20d0f3a"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "lecture_videos",
        sa.Column(
            "video_description_duration_ms",
            sa.Integer(),
            nullable=False,
            server_default="30000",
        ),
    )


def downgrade() -> None:
    op.drop_column("lecture_videos", "video_description_duration_ms")

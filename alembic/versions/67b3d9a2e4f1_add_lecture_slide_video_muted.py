"""Add muted video narration to lecture slides.

Revision ID: 67b3d9a2e4f1
Revises: 3b62b41855a2
"""

from alembic import op
import sqlalchemy as sa

revision = "67b3d9a2e4f1"
down_revision = "3b62b41855a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lecture_slide_pages",
        sa.Column(
            "video_muted", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("lecture_slide_pages", "video_muted")

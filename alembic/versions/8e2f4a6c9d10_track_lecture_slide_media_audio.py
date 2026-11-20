"""Track whether lecture slide media has original audio.

Revision ID: 8e2f4a6c9d10
Revises: 67b3d9a2e4f1
"""

from alembic import op
import sqlalchemy as sa

revision = "8e2f4a6c9d10"
down_revision = "67b3d9a2e4f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing inserted videos were required to have an audio track.
    op.add_column(
        "lecture_slide_media_stored_objects",
        sa.Column("has_audio", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("lecture_slide_media_stored_objects", "has_audio")

"""add elevenlabs voice settings

Revision ID: c6a4f8d2b901
Revises: b35ad7a2f2d1
Create Date: 2026-05-05 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c6a4f8d2b901"
down_revision: Union[str, None] = "b35ad7a2f2d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_ELEVENLABS_STABILITY = 0.5
DEFAULT_ELEVENLABS_SIMILARITY_BOOST = 0.8
DEFAULT_ELEVENLABS_USE_SPEAKER_BOOST = True
DEFAULT_ELEVENLABS_STYLE = 0.0
DEFAULT_ELEVENLABS_SPEED = 1.0


def _backfill_elevenlabs_voice_settings() -> None:
    table = sa.table(
        "assistants",
        sa.column("id", sa.Integer()),
        sa.column("interaction_mode", sa.String()),
        sa.column("elevenlabs_stability", sa.Float()),
        sa.column("elevenlabs_similarity_boost", sa.Float()),
        sa.column("elevenlabs_use_speaker_boost", sa.Boolean()),
        sa.column("elevenlabs_style", sa.Float()),
        sa.column("elevenlabs_speed", sa.Float()),
    )
    op.get_bind().execute(
        table.update()
        .where(
            sa.and_(
                table.c.interaction_mode == "LECTURE_VIDEO",
                sa.or_(
                    table.c.elevenlabs_stability.is_(None),
                    table.c.elevenlabs_similarity_boost.is_(None),
                    table.c.elevenlabs_use_speaker_boost.is_(None),
                    table.c.elevenlabs_style.is_(None),
                    table.c.elevenlabs_speed.is_(None),
                ),
            )
        )
        .values(
            elevenlabs_stability=DEFAULT_ELEVENLABS_STABILITY,
            elevenlabs_similarity_boost=DEFAULT_ELEVENLABS_SIMILARITY_BOOST,
            elevenlabs_use_speaker_boost=DEFAULT_ELEVENLABS_USE_SPEAKER_BOOST,
            elevenlabs_style=DEFAULT_ELEVENLABS_STYLE,
            elevenlabs_speed=DEFAULT_ELEVENLABS_SPEED,
        )
    )


def upgrade() -> None:
    op.add_column(
        "assistants", sa.Column("elevenlabs_stability", sa.Float(), nullable=True)
    )
    op.add_column(
        "assistants",
        sa.Column("elevenlabs_similarity_boost", sa.Float(), nullable=True),
    )
    op.add_column(
        "assistants",
        sa.Column("elevenlabs_use_speaker_boost", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "assistants", sa.Column("elevenlabs_style", sa.Float(), nullable=True)
    )
    op.add_column(
        "assistants", sa.Column("elevenlabs_speed", sa.Float(), nullable=True)
    )
    _backfill_elevenlabs_voice_settings()


def downgrade() -> None:
    op.drop_column("assistants", "elevenlabs_speed")
    op.drop_column("assistants", "elevenlabs_style")
    op.drop_column("assistants", "elevenlabs_use_speaker_boost")
    op.drop_column("assistants", "elevenlabs_similarity_boost")
    op.drop_column("assistants", "elevenlabs_stability")

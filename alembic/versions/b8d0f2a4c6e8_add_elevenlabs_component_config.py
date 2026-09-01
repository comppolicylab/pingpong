"""add ElevenLabs component configuration

Revision ID: b8d0f2a4c6e8
Revises: a7c9e1f2b4d6
Create Date: 2026-08-31

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b8d0f2a4c6e8"
down_revision: str | None = "a7c9e1f2b4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FLASH_MODEL = "eleven_flash_v2_5"
V3_MODEL = "eleven_v3"
DEFAULT_FLASH_PROFILE = {
    "model": FLASH_MODEL,
    "stability": 0.5,
    "similarity_boost": 0.8,
    "use_speaker_boost": True,
    "style": 0.0,
    "speed": 1.0,
}
DEFAULT_V3_PROFILE = {**DEFAULT_FLASH_PROFILE, "model": V3_MODEL}


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on

    op.add_column(
        "assistants",
        sa.Column("elevenlabs_config", sa.JSON(), nullable=True),
    )

    connection = op.get_bind()
    assistants = sa.table(
        "assistants",
        sa.column("id", sa.Integer()),
        sa.column("interaction_mode", sa.String()),
        sa.column("elevenlabs_stability", sa.Float()),
        sa.column("elevenlabs_similarity_boost", sa.Float()),
        sa.column("elevenlabs_use_speaker_boost", sa.Boolean()),
        sa.column("elevenlabs_style", sa.Float()),
        sa.column("elevenlabs_speed", sa.Float()),
        sa.column("elevenlabs_config", sa.JSON()),
    )
    rows = connection.execute(
        sa.select(
            assistants.c.id,
            assistants.c.elevenlabs_stability,
            assistants.c.elevenlabs_similarity_boost,
            assistants.c.elevenlabs_use_speaker_boost,
            assistants.c.elevenlabs_style,
            assistants.c.elevenlabs_speed,
        ).where(assistants.c.interaction_mode.in_(["LECTURE_VIDEO", "LECTURE_SLIDES"]))
    )
    for row in rows:
        live_chat = {
            **DEFAULT_FLASH_PROFILE,
            "stability": (
                row.elevenlabs_stability
                if row.elevenlabs_stability is not None
                else DEFAULT_FLASH_PROFILE["stability"]
            ),
            "similarity_boost": (
                row.elevenlabs_similarity_boost
                if row.elevenlabs_similarity_boost is not None
                else DEFAULT_FLASH_PROFILE["similarity_boost"]
            ),
            "use_speaker_boost": (
                row.elevenlabs_use_speaker_boost
                if row.elevenlabs_use_speaker_boost is not None
                else DEFAULT_FLASH_PROFILE["use_speaker_boost"]
            ),
            "style": (
                row.elevenlabs_style
                if row.elevenlabs_style is not None
                else DEFAULT_FLASH_PROFILE["style"]
            ),
            "speed": (
                row.elevenlabs_speed
                if row.elevenlabs_speed is not None
                else DEFAULT_FLASH_PROFILE["speed"]
            ),
        }
        config = {
            "version": 1,
            "narration": dict(DEFAULT_V3_PROFILE),
            "knowledge_check": dict(DEFAULT_V3_PROFILE),
            "live_chat": live_chat,
            "pronunciation_cache": {},
        }
        connection.execute(
            sa.update(assistants)
            .where(assistants.c.id == row.id)
            .values(elevenlabs_config=config)
        )


def downgrade() -> None:
    op.drop_column("assistants", "elevenlabs_config")

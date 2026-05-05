"""add realtime voice settings

Revision ID: b35ad7a2f2d1
Revises: a557c213b631
Create Date: 2026-05-05 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b35ad7a2f2d1"
down_revision: Union[str, None] = "a557c213b631"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


realtime_eagerness = sa.Enum(
    "LOW",
    "MEDIUM",
    "HIGH",
    "AUTO",
    name="realtimeeagerness",
)
realtime_vad_mode = sa.Enum(
    "SEMANTIC_VAD",
    "SERVER_VAD",
    name="realtimevadmode",
)
realtime_voice = sa.Enum(
    "ALLOY",
    "ASH",
    "BALLAD",
    "CORAL",
    "ECHO",
    "SAGE",
    "SHIMMER",
    "VERSE",
    "MARIN",
    "CEDAR",
    name="realtimevoice",
)
realtime_noise_reduction = sa.Enum(
    "NEAR_FIELD",
    "FAR_FIELD",
    "NONE",
    name="realtimenoisereduction",
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    bind = op.get_bind()
    realtime_vad_mode.create(bind, checkfirst=True)
    realtime_eagerness.create(bind, checkfirst=True)
    realtime_voice.create(bind, checkfirst=True)
    realtime_noise_reduction.create(bind, checkfirst=True)
    op.add_column(
        "assistants",
        sa.Column("realtime_vad_mode", realtime_vad_mode, nullable=True),
    )
    op.add_column(
        "assistants",
        sa.Column(
            "realtime_eagerness",
            realtime_eagerness,
            nullable=True,
        ),
    )
    op.add_column(
        "assistants", sa.Column("realtime_vad_threshold", sa.Float(), nullable=True)
    )
    op.add_column(
        "assistants",
        sa.Column("realtime_vad_prefix_padding_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "assistants",
        sa.Column("realtime_vad_silence_duration_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "assistants",
        sa.Column("realtime_vad_idle_timeout_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "assistants",
        sa.Column("realtime_voice", realtime_voice, nullable=True),
    )
    op.add_column("assistants", sa.Column("realtime_speed", sa.Float(), nullable=True))
    op.add_column(
        "assistants",
        sa.Column(
            "realtime_noise_reduction",
            realtime_noise_reduction,
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("assistants", "realtime_noise_reduction")
    op.drop_column("assistants", "realtime_speed")
    op.drop_column("assistants", "realtime_voice")
    op.drop_column("assistants", "realtime_vad_idle_timeout_ms")
    op.drop_column("assistants", "realtime_vad_silence_duration_ms")
    op.drop_column("assistants", "realtime_vad_prefix_padding_ms")
    op.drop_column("assistants", "realtime_vad_threshold")
    op.drop_column("assistants", "realtime_eagerness")
    op.drop_column("assistants", "realtime_vad_mode")
    realtime_noise_reduction.drop(op.get_bind(), checkfirst=True)
    realtime_voice.drop(op.get_bind(), checkfirst=True)
    realtime_eagerness.drop(op.get_bind(), checkfirst=True)
    realtime_vad_mode.drop(op.get_bind(), checkfirst=True)

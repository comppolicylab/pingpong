"""add realtime transcription model

Revision ID: 4a9d7c3e2f10
Revises: c6a4f8d2b901
Create Date: 2026-05-19 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4a9d7c3e2f10"
down_revision: Union[str, None] = "c6a4f8d2b901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


realtime_transcription_model = sa.Enum(
    "WHISPER_1",
    "GPT_REALTIME_WHISPER",
    name="realtimetranscriptionmodel",
)


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on

    realtime_transcription_model.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "assistants",
        sa.Column(
            "realtime_transcription_model",
            realtime_transcription_model,
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("assistants", "realtime_transcription_model")
    realtime_transcription_model.drop(op.get_bind(), checkfirst=True)

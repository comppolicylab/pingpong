"""Add class credentials

Revision ID: 86d7206db7f1
Revises: 0a1c5d9b7e44
Create Date: 2026-03-14 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "86d7206db7f1"
down_revision: Union[str, None] = "0a1c5d9b7e44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


class_credential_purpose_enum = sa.Enum(
    "LECTURE_VIDEO_NARRATION_TTS",
    "LECTURE_VIDEO_MANIFEST_GENERATION",
    name="classcredentialpurpose",
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.create_table(
        "class_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("purpose", class_credential_purpose_enum, nullable=False),
        sa.Column("api_key_id", sa.Integer(), nullable=False),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"]),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("class_id", "purpose", name="_class_purpose_credential_uc"),
    )


def downgrade() -> None:
    op.drop_table("class_credentials")
    class_credential_purpose_enum.drop(op.get_bind(), checkfirst=False)

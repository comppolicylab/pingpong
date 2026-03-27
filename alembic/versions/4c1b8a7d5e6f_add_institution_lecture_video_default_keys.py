"""Add institution lecture video default API keys

Revision ID: 4c1b8a7d5e6f
Revises: 7cb4d6c2b8f1
Create Date: 2026-03-27 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4c1b8a7d5e6f"
down_revision: Union[str, None] = "7cb4d6c2b8f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.add_column(
        "institutions",
        sa.Column("default_lv_narration_tts_api_key_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "institutions",
        sa.Column(
            "default_lv_manifest_generation_api_key_id", sa.Integer(), nullable=True
        ),
    )
    op.create_foreign_key(
        "institutions_default_lv_narration_tts_api_key_id_fkey",
        "institutions",
        "api_keys",
        ["default_lv_narration_tts_api_key_id"],
        ["id"],
    )
    op.create_foreign_key(
        "institutions_default_lv_manifest_generation_api_key_id_fkey",
        "institutions",
        "api_keys",
        ["default_lv_manifest_generation_api_key_id"],
        ["id"],
    )
    op.create_index(
        "ix_institutions_default_lv_narration_tts_api_key_id",
        "institutions",
        ["default_lv_narration_tts_api_key_id"],
    )
    op.create_index(
        "ix_institutions_default_lv_manifest_generation_api_key_id",
        "institutions",
        ["default_lv_manifest_generation_api_key_id"],
    )


def downgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.drop_index(
        "ix_institutions_default_lv_manifest_generation_api_key_id",
        table_name="institutions",
    )
    op.drop_index(
        "ix_institutions_default_lv_narration_tts_api_key_id",
        table_name="institutions",
    )
    op.drop_constraint(
        "institutions_default_lv_manifest_generation_api_key_id_fkey",
        "institutions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "institutions_default_lv_narration_tts_api_key_id_fkey",
        "institutions",
        type_="foreignkey",
    )
    op.drop_column("institutions", "default_lv_manifest_generation_api_key_id")
    op.drop_column("institutions", "default_lv_narration_tts_api_key_id")

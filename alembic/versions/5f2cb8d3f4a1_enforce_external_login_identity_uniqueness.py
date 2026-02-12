"""Enforce external login identity uniqueness

Revision ID: 5f2cb8d3f4a1
Revises: 3cc56efe20a8
Create Date: 2026-02-12 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5f2cb8d3f4a1"
down_revision: Union[str, None] = "3cc56efe20a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _assert_no_provider_identifier_duplicates() -> None:
    bind = op.get_bind()
    duplicate_provider_identifier = bind.execute(
        sa.text(
            """
            SELECT provider, identifier, COUNT(DISTINCT user_id) AS user_count
            FROM external_logins
            GROUP BY provider, identifier
            HAVING COUNT(DISTINCT user_id) > 1
            LIMIT 5
            """
        )
    ).fetchall()
    if duplicate_provider_identifier:
        sample = ", ".join(
            f"{row.provider}:{row.identifier}" for row in duplicate_provider_identifier
        )
        raise RuntimeError(
            "Cannot enforce external login uniqueness; duplicate (provider, identifier) "
            f"pairs still exist across users. Sample: {sample}"
        )

    duplicate_provider_id_identifier = bind.execute(
        sa.text(
            """
            SELECT provider_id, identifier, COUNT(DISTINCT user_id) AS user_count
            FROM external_logins
            WHERE provider_id IS NOT NULL
            GROUP BY provider_id, identifier
            HAVING COUNT(DISTINCT user_id) > 1
            LIMIT 5
            """
        )
    ).fetchall()
    if duplicate_provider_id_identifier:
        sample = ", ".join(
            f"{row.provider_id}:{row.identifier}"
            for row in duplicate_provider_id_identifier
        )
        raise RuntimeError(
            "Cannot enforce external login uniqueness; duplicate "
            "(provider_id, identifier) pairs still exist across users. "
            f"Sample: {sample}"
        )


def upgrade() -> None:
    _assert_no_provider_identifier_duplicates()
    op.create_unique_constraint(
        "uq_external_logins_provider_identifier",
        "external_logins",
        ["provider", "identifier"],
    )
    op.create_unique_constraint(
        "uq_external_logins_provider_id_identifier_global",
        "external_logins",
        ["provider_id", "identifier"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_external_logins_provider_id_identifier_global",
        "external_logins",
        type_="unique",
    )
    op.drop_constraint(
        "uq_external_logins_provider_identifier",
        "external_logins",
        type_="unique",
    )

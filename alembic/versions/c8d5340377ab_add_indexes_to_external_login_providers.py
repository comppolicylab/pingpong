"""Add indexes to external_login_providers

Revision ID: c8d5340377ab
Revises: 867fefaae27b
Create Date: 2026-02-09 15:06:24.656748

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c8d5340377ab"
down_revision: Union[str, None] = "867fefaae27b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_name_index = next(
        (
            index
            for index in inspector.get_indexes("external_login_providers")
            if index["name"] == "ix_external_login_providers_name"
        ),
        None,
    )

    if existing_name_index:
        if not existing_name_index.get("unique", False):
            op.drop_index(
                "ix_external_login_providers_name",
                table_name="external_login_providers",
            )
            op.create_index(
                "ix_external_login_providers_name",
                "external_login_providers",
                ["name"],
                unique=True,
            )
    else:
        op.create_index(
            "ix_external_login_providers_name",
            "external_login_providers",
            ["name"],
            unique=True,
        )

    op.create_index(
        "idx_provider_id_identifier",
        "external_logins",
        ["provider_id", "identifier"],
        unique=False,
    )
    op.create_index(
        "idx_provider_identifier",
        "external_logins",
        ["provider", "identifier"],
        unique=False,
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_index("idx_provider_identifier", table_name="external_logins")
    op.drop_index("idx_provider_id_identifier", table_name="external_logins")
    op.drop_index(
        "ix_external_login_providers_name", table_name="external_login_providers"
    )
    op.create_index(
        "ix_external_login_providers_name",
        "external_login_providers",
        ["name"],
        unique=False,
    )

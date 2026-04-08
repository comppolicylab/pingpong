"""Add safety identifier UUID columns

Revision ID: 2f9a6b7e8c31
Revises: ff54a796106b
Create Date: 2026-04-08 13:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import uuid


# revision identifiers, used by Alembic.
revision: str = "2f9a6b7e8c31"
down_revision: Union[str, None] = "ff54a796106b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_safety_identifier_uuids(table_name: str) -> None:
    table = sa.table(
        table_name,
        sa.column("id", sa.Integer()),
        sa.column("safety_identifier_uuid", sa.String()),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(table.c.id).where(table.c.safety_identifier_uuid.is_(None))
    ).fetchall()
    for row in rows:
        bind.execute(
            table.update()
            .where(table.c.id == row.id)
            .values(safety_identifier_uuid=str(uuid.uuid4()))
        )


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.add_column(
        "users", sa.Column("safety_identifier_uuid", sa.String(), nullable=True)
    )
    op.add_column(
        "anonymous_sessions",
        sa.Column("safety_identifier_uuid", sa.String(), nullable=True),
    )
    op.add_column(
        "anonymous_links",
        sa.Column("safety_identifier_uuid", sa.String(), nullable=True),
    )
    _backfill_safety_identifier_uuids("users")
    _backfill_safety_identifier_uuids("anonymous_sessions")
    _backfill_safety_identifier_uuids("anonymous_links")


def downgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.drop_column("anonymous_links", "safety_identifier_uuid")
    op.drop_column("anonymous_sessions", "safety_identifier_uuid")
    op.drop_column("users", "safety_identifier_uuid")

"""Add lecture slide interaction mode

Revision ID: a2d9e4f6b7c8
Revises: 8fb2a14e9c6d
Create Date: 2026-05-29 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a2d9e4f6b7c8"
down_revision: Union[str, None] = "8fb2a14e9c6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


enum_name = "interactionmode"
temp_enum_name = f"temp_{enum_name}"
old_values = ("CHAT", "VOICE", "LECTURE_VIDEO")
new_values = (*old_values, "LECTURE_SLIDES")
old_type = sa.Enum(*old_values, name=enum_name)
new_type = sa.Enum(*new_values, name=enum_name)
temp_type = sa.Enum(*new_values, name=temp_enum_name)

column_name = "interaction_mode"

assistants_table = "assistants"
assistants_simplified = sa.sql.table(
    assistants_table, sa.Column(column_name, new_type, nullable=False)
)

threads_table = "threads"
threads_simplified = sa.sql.table(
    threads_table, sa.Column(column_name, new_type, nullable=False)
)


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on

    op.execute(
        f"ALTER TABLE {assistants_table} ALTER COLUMN {column_name} DROP DEFAULT"
    )
    op.execute(f"ALTER TABLE {threads_table} ALTER COLUMN {column_name} DROP DEFAULT")

    temp_type.create(op.get_bind(), checkfirst=False)

    with op.batch_alter_table(assistants_table) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=old_type,
            type_=temp_type,
            postgresql_using=f"{column_name}::text::{temp_enum_name}",
            existing_nullable=False,
        )

    with op.batch_alter_table(threads_table) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=old_type,
            type_=temp_type,
            postgresql_using=f"{column_name}::text::{temp_enum_name}",
            existing_nullable=False,
        )

    old_type.drop(op.get_bind(), checkfirst=False)
    new_type.create(op.get_bind(), checkfirst=False)

    with op.batch_alter_table(assistants_table) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=temp_type,
            type_=new_type,
            postgresql_using=f"{column_name}::text::{enum_name}",
            existing_nullable=False,
        )

    with op.batch_alter_table(threads_table) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=temp_type,
            type_=new_type,
            postgresql_using=f"{column_name}::text::{enum_name}",
            existing_nullable=False,
        )

    temp_type.drop(op.get_bind(), checkfirst=False)

    op.execute(
        f"ALTER TABLE {assistants_table} ALTER COLUMN {column_name} SET DEFAULT 'CHAT'::{enum_name}"
    )
    op.execute(
        f"ALTER TABLE {threads_table} ALTER COLUMN {column_name} SET DEFAULT 'CHAT'::{enum_name}"
    )


def downgrade() -> None:
    op.execute(
        threads_simplified.delete().where(
            threads_simplified.c.interaction_mode == "LECTURE_SLIDES"
        )
    )
    op.execute(
        assistants_simplified.delete().where(
            assistants_simplified.c.interaction_mode == "LECTURE_SLIDES"
        )
    )

    op.execute(
        f"ALTER TABLE {assistants_table} ALTER COLUMN {column_name} DROP DEFAULT"
    )
    op.execute(f"ALTER TABLE {threads_table} ALTER COLUMN {column_name} DROP DEFAULT")

    temp_type.create(op.get_bind(), checkfirst=False)

    with op.batch_alter_table(assistants_table) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=new_type,
            type_=temp_type,
            postgresql_using=f"{column_name}::text::{temp_enum_name}",
            existing_nullable=False,
        )

    with op.batch_alter_table(threads_table) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=new_type,
            type_=temp_type,
            postgresql_using=f"{column_name}::text::{temp_enum_name}",
            existing_nullable=False,
        )

    new_type.drop(op.get_bind(), checkfirst=False)
    old_type.create(op.get_bind(), checkfirst=False)

    with op.batch_alter_table(assistants_table) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=temp_type,
            type_=old_type,
            postgresql_using=f"{column_name}::text::{enum_name}",
            existing_nullable=False,
        )

    with op.batch_alter_table(threads_table) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=temp_type,
            type_=old_type,
            postgresql_using=f"{column_name}::text::{enum_name}",
            existing_nullable=False,
        )

    temp_type.drop(op.get_bind(), checkfirst=False)

    op.execute(
        f"ALTER TABLE {assistants_table} ALTER COLUMN {column_name} SET DEFAULT 'CHAT'::{enum_name}"
    )
    op.execute(
        f"ALTER TABLE {threads_table} ALTER COLUMN {column_name} SET DEFAULT 'CHAT'::{enum_name}"
    )

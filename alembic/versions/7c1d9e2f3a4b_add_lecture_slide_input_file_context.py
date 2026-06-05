"""Add lecture slide input file context

Revision ID: 7c1d9e2f3a4b
Revises: 6e1f8c9a4d2b
Create Date: 2026-06-04 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c1d9e2f3a4b"
down_revision: Union[str, None] = "6e1f8c9a4d2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


enum_name = "messageparttype"
temp_enum_name = f"temp_{enum_name}"
old_values = ("INPUT_TEXT", "INPUT_IMAGE", "OUTPUT_TEXT", "REFUSAL")
new_values = ("INPUT_TEXT", "INPUT_IMAGE", "INPUT_FILE", "OUTPUT_TEXT", "REFUSAL")
old_type = sa.Enum(*old_values, name=enum_name)
new_type = sa.Enum(*new_values, name=enum_name)
temp_type = sa.Enum(*new_values, name=temp_enum_name)


def _replace_message_part_type(bind, from_type: sa.Enum, to_type: sa.Enum) -> None:
    temp_type.create(bind, checkfirst=False)
    with op.batch_alter_table("message_parts") as batch_op:
        batch_op.alter_column(
            "type",
            existing_type=from_type,
            type_=temp_type,
            postgresql_using=f"type::text::{temp_enum_name}",
            existing_nullable=False,
        )
    from_type.drop(bind, checkfirst=False)
    to_type.create(bind, checkfirst=False)
    with op.batch_alter_table("message_parts") as batch_op:
        batch_op.alter_column(
            "type",
            existing_type=temp_type,
            type_=to_type,
            postgresql_using=f"type::text::{enum_name}",
            existing_nullable=False,
        )
    temp_type.drop(bind, checkfirst=False)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    with op.batch_alter_table("lecture_slide_source_stored_objects") as batch_op:
        batch_op.add_column(
            sa.Column("openai_file_object_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_ls_source_openai_file_object_id",
            "files",
            ["openai_file_object_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("message_parts") as batch_op:
        batch_op.add_column(
            sa.Column("input_file_object_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_message_parts_input_file_object_id",
            "files",
            ["input_file_object_id"],
            ["id"],
            ondelete="SET NULL",
        )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _replace_message_part_type(bind, old_type, new_type)


def downgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.execute(sa.text("DELETE FROM message_parts WHERE type = 'INPUT_FILE'"))

    with op.batch_alter_table("message_parts") as batch_op:
        batch_op.drop_constraint(
            "fk_message_parts_input_file_object_id", type_="foreignkey"
        )
        batch_op.drop_column("input_file_object_id")
    with op.batch_alter_table("lecture_slide_source_stored_objects") as batch_op:
        batch_op.drop_constraint(
            "fk_ls_source_openai_file_object_id", type_="foreignkey"
        )
        batch_op.drop_column("openai_file_object_id")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _replace_message_part_type(bind, new_type, old_type)

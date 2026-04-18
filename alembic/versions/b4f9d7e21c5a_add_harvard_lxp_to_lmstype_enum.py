"""Add HARVARD_LXP to lmstype enum

Revision ID: b4f9d7e21c5a
Revises: c7d3a9e12b84
Create Date: 2026-04-17 11:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b4f9d7e21c5a"
down_revision: Union[str, None] = "c7d3a9e12b84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


enum_name = "lmstype"
temp_enum_name = f"temp_{enum_name}"
old_values = ("CANVAS",)
new_values = ("CANVAS", "HARVARD_LXP")
old_type = sa.Enum(*old_values, name=enum_name)
new_type = sa.Enum(*new_values, name=enum_name)
temp_type = sa.Enum(*new_values, name=temp_enum_name)

users_classes_table = sa.sql.table(
    "users_classes", sa.Column("lms_type", new_type, nullable=True)
)
classes_table = sa.sql.table(
    "classes",
    sa.Column("lms_type", new_type, nullable=True),
    sa.Column("lms_class_id", sa.Integer(), nullable=True),
)
lms_classes_table = sa.sql.table(
    "lms_classes",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("lms_type", new_type, nullable=False),
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on
    temp_type.create(op.get_bind(), checkfirst=False)

    with op.batch_alter_table("users_classes") as batch_op:
        batch_op.alter_column(
            "lms_type",
            existing_type=old_type,
            type_=temp_type,
            postgresql_using=f"lms_type::text::{temp_enum_name}",
            existing_nullable=True,
        )
    with op.batch_alter_table("classes") as batch_op:
        batch_op.alter_column(
            "lms_type",
            existing_type=old_type,
            type_=temp_type,
            postgresql_using=f"lms_type::text::{temp_enum_name}",
            existing_nullable=True,
        )
    with op.batch_alter_table("lms_classes") as batch_op:
        batch_op.alter_column(
            "lms_type",
            existing_type=old_type,
            type_=temp_type,
            postgresql_using=f"lms_type::text::{temp_enum_name}",
            existing_nullable=False,
        )

    old_type.drop(op.get_bind(), checkfirst=False)
    new_type.create(op.get_bind(), checkfirst=False)

    with op.batch_alter_table("users_classes") as batch_op:
        batch_op.alter_column(
            "lms_type",
            existing_type=temp_type,
            type_=new_type,
            postgresql_using=f"lms_type::text::{enum_name}",
            existing_nullable=True,
        )
    with op.batch_alter_table("classes") as batch_op:
        batch_op.alter_column(
            "lms_type",
            existing_type=temp_type,
            type_=new_type,
            postgresql_using=f"lms_type::text::{enum_name}",
            existing_nullable=True,
        )
    with op.batch_alter_table("lms_classes") as batch_op:
        batch_op.alter_column(
            "lms_type",
            existing_type=temp_type,
            type_=new_type,
            postgresql_using=f"lms_type::text::{enum_name}",
            existing_nullable=False,
        )

    temp_type.drop(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    harvard_lxp_lms_class_ids = sa.select(lms_classes_table.c.id).where(
        lms_classes_table.c.lms_type == "HARVARD_LXP"
    )

    op.execute(
        users_classes_table.update()
        .where(users_classes_table.c.lms_type == "HARVARD_LXP")
        .values(lms_type=None)
    )
    op.execute(
        classes_table.update()
        .where(classes_table.c.lms_type == "HARVARD_LXP")
        .values(lms_type=None)
    )
    op.execute(
        classes_table.update()
        .where(classes_table.c.lms_class_id.in_(harvard_lxp_lms_class_ids))
        .values(lms_class_id=None)
    )
    op.execute(
        lms_classes_table.delete().where(lms_classes_table.c.lms_type == "HARVARD_LXP")
    )

    temp_type.create(op.get_bind(), checkfirst=False)

    with op.batch_alter_table("users_classes") as batch_op:
        batch_op.alter_column(
            "lms_type",
            existing_type=new_type,
            type_=temp_type,
            postgresql_using=f"lms_type::text::{temp_enum_name}",
            existing_nullable=True,
        )
    with op.batch_alter_table("classes") as batch_op:
        batch_op.alter_column(
            "lms_type",
            existing_type=new_type,
            type_=temp_type,
            postgresql_using=f"lms_type::text::{temp_enum_name}",
            existing_nullable=True,
        )
    with op.batch_alter_table("lms_classes") as batch_op:
        batch_op.alter_column(
            "lms_type",
            existing_type=new_type,
            type_=temp_type,
            postgresql_using=f"lms_type::text::{temp_enum_name}",
            existing_nullable=False,
        )

    new_type.drop(op.get_bind(), checkfirst=False)
    old_type.create(op.get_bind(), checkfirst=False)

    with op.batch_alter_table("users_classes") as batch_op:
        batch_op.alter_column(
            "lms_type",
            existing_type=temp_type,
            type_=old_type,
            postgresql_using=f"lms_type::text::{enum_name}",
            existing_nullable=True,
        )
    with op.batch_alter_table("classes") as batch_op:
        batch_op.alter_column(
            "lms_type",
            existing_type=temp_type,
            type_=old_type,
            postgresql_using=f"lms_type::text::{enum_name}",
            existing_nullable=True,
        )
    with op.batch_alter_table("lms_classes") as batch_op:
        batch_op.alter_column(
            "lms_type",
            existing_type=temp_type,
            type_=old_type,
            postgresql_using=f"lms_type::text::{enum_name}",
            existing_nullable=False,
        )

    temp_type.drop(op.get_bind(), checkfirst=False)

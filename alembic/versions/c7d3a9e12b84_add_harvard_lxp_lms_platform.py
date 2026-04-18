"""Add HARVARD_LXP to lmsplatform enum

Revision ID: c7d3a9e12b84
Revises: 2f9a6b7e8c31
Create Date: 2026-04-16 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7d3a9e12b84"
down_revision: Union[str, None] = "2f9a6b7e8c31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


enum_name = "lmsplatform"
temp_enum_name = f"temp_{enum_name}"
old_values = ("CANVAS",)
new_values = ("CANVAS", "HARVARD_LXP")
old_type = sa.Enum(*old_values, name=enum_name)
new_type = sa.Enum(*new_values, name=enum_name)
temp_type = sa.Enum(*new_values, name=temp_enum_name)

lti_classes_table = sa.sql.table(
    "lti_classes", sa.Column("lti_platform", new_type, nullable=False)
)
lti_registrations_table = sa.sql.table(
    "lti_registrations", sa.Column("lms_platform", new_type, nullable=True)
)


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    temp_type.create(op.get_bind(), checkfirst=False)

    with op.batch_alter_table("lti_classes") as batch_op:
        batch_op.alter_column(
            "lti_platform",
            existing_type=old_type,
            type_=temp_type,
            postgresql_using=f"lti_platform::text::{temp_enum_name}",
            existing_nullable=False,
        )
    with op.batch_alter_table("lti_registrations") as batch_op:
        batch_op.alter_column(
            "lms_platform",
            existing_type=old_type,
            type_=temp_type,
            postgresql_using=f"lms_platform::text::{temp_enum_name}",
            existing_nullable=True,
        )

    old_type.drop(op.get_bind(), checkfirst=False)
    new_type.create(op.get_bind(), checkfirst=False)

    with op.batch_alter_table("lti_classes") as batch_op:
        batch_op.alter_column(
            "lti_platform",
            existing_type=temp_type,
            type_=new_type,
            postgresql_using=f"lti_platform::text::{enum_name}",
            existing_nullable=False,
        )
    with op.batch_alter_table("lti_registrations") as batch_op:
        batch_op.alter_column(
            "lms_platform",
            existing_type=temp_type,
            type_=new_type,
            postgresql_using=f"lms_platform::text::{enum_name}",
            existing_nullable=True,
        )

    temp_type.drop(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    op.execute(
        lti_classes_table.delete().where(
            lti_classes_table.c.lti_platform == "HARVARD_LXP"
        )
    )
    op.execute(
        lti_registrations_table.delete().where(
            lti_registrations_table.c.lms_platform == "HARVARD_LXP"
        )
    )

    temp_type.create(op.get_bind(), checkfirst=False)

    with op.batch_alter_table("lti_classes") as batch_op:
        batch_op.alter_column(
            "lti_platform",
            existing_type=new_type,
            type_=temp_type,
            postgresql_using=f"lti_platform::text::{temp_enum_name}",
            existing_nullable=False,
        )
    with op.batch_alter_table("lti_registrations") as batch_op:
        batch_op.alter_column(
            "lms_platform",
            existing_type=new_type,
            type_=temp_type,
            postgresql_using=f"lms_platform::text::{temp_enum_name}",
            existing_nullable=True,
        )

    new_type.drop(op.get_bind(), checkfirst=False)
    old_type.create(op.get_bind(), checkfirst=False)

    with op.batch_alter_table("lti_classes") as batch_op:
        batch_op.alter_column(
            "lti_platform",
            existing_type=temp_type,
            type_=old_type,
            postgresql_using=f"lti_platform::text::{enum_name}",
            existing_nullable=False,
        )
    with op.batch_alter_table("lti_registrations") as batch_op:
        batch_op.alter_column(
            "lms_platform",
            existing_type=temp_type,
            type_=old_type,
            postgresql_using=f"lms_platform::text::{enum_name}",
            existing_nullable=True,
        )

    temp_type.drop(op.get_bind(), checkfirst=False)

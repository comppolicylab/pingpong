"""Add manual manifest replaced cancel reason

Revision ID: c1e4f3a8b9d2
Revises: 9c7e1d6a4b2f
Create Date: 2026-04-26 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1e4f3a8b9d2"
down_revision: Union[str, None] = "9c7e1d6a4b2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


enum_name = "lecturevideoprocessingcancelreason"
temp_enum_name = f"temp_{enum_name}"
old_values = ("ASSISTANT_DETACHED", "ASSISTANT_DELETED", "LECTURE_VIDEO_DELETED")
new_values = (*old_values, "MANUAL_MANIFEST_REPLACED")
old_type = sa.Enum(*old_values, name=enum_name)
new_type = sa.Enum(*new_values, name=enum_name)
temp_type = sa.Enum(*new_values, name=temp_enum_name)

lecture_video_processing_runs_table = sa.sql.table(
    "lecture_video_processing_runs",
    sa.Column("cancel_reason", new_type, nullable=True),
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    temp_type.create(bind, checkfirst=False)

    with op.batch_alter_table("lecture_video_processing_runs") as batch_op:
        batch_op.alter_column(
            "cancel_reason",
            existing_type=old_type,
            type_=temp_type,
            postgresql_using=f"cancel_reason::text::{temp_enum_name}",
            existing_nullable=True,
        )

    old_type.drop(bind, checkfirst=False)
    new_type.create(bind, checkfirst=False)

    with op.batch_alter_table("lecture_video_processing_runs") as batch_op:
        batch_op.alter_column(
            "cancel_reason",
            existing_type=temp_type,
            type_=new_type,
            postgresql_using=f"cancel_reason::text::{enum_name}",
            existing_nullable=True,
        )

    temp_type.drop(bind, checkfirst=False)


def downgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        lecture_video_processing_runs_table.update()
        .where(
            lecture_video_processing_runs_table.c.cancel_reason
            == "MANUAL_MANIFEST_REPLACED"
        )
        .values(cancel_reason=None)
    )

    temp_type.create(bind, checkfirst=False)

    with op.batch_alter_table("lecture_video_processing_runs") as batch_op:
        batch_op.alter_column(
            "cancel_reason",
            existing_type=new_type,
            type_=temp_type,
            postgresql_using=f"cancel_reason::text::{temp_enum_name}",
            existing_nullable=True,
        )

    new_type.drop(bind, checkfirst=False)
    old_type.create(bind, checkfirst=False)

    with op.batch_alter_table("lecture_video_processing_runs") as batch_op:
        batch_op.alter_column(
            "cancel_reason",
            existing_type=temp_type,
            type_=old_type,
            postgresql_using=f"cancel_reason::text::{enum_name}",
            existing_nullable=True,
        )

    temp_type.drop(bind, checkfirst=False)

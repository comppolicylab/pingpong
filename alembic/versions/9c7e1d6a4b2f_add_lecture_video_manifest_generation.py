"""Add lecture video manifest generation

Revision ID: 9c7e1d6a4b2f
Revises: b4f9d7e21c5a
Create Date: 2026-04-26 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c7e1d6a4b2f"
down_revision: Union[str, None] = "b4f9d7e21c5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


enum_name = "lecturevideoprocessingstage"
temp_enum_name = f"temp_{enum_name}"
old_values = ("NARRATION",)
new_values = ("NARRATION", "MANIFEST_GENERATION")
old_stage_type = sa.Enum(*old_values, name=enum_name)
new_stage_type = sa.Enum(*new_values, name=enum_name)
temp_stage_type = sa.Enum(*new_values, name=temp_enum_name)

lecture_video_processing_runs_table = sa.sql.table(
    "lecture_video_processing_runs",
    sa.Column("stage", new_stage_type, nullable=False),
)
lecture_videos_table = sa.sql.table(
    "lecture_videos",
    sa.Column("manifest_data", sa.JSON(), nullable=True),
    sa.Column("manual_manifest", sa.Boolean(), nullable=False),
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    op.add_column(
        "lecture_videos",
        sa.Column("generation_prompt", sa.Text(), nullable=True),
    )
    op.add_column(
        "lecture_videos",
        sa.Column(
            "manual_manifest",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.execute(
        sqlalchemy.update(lecture_videos_table)
        .where(lecture_videos_table.c.manifest_data.is_not(None))
        .values(manual_manifest=True)
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        temp_stage_type.create(bind, checkfirst=False)

        with op.batch_alter_table("lecture_video_processing_runs") as batch_op:
            batch_op.alter_column(
                "stage",
                existing_type=old_stage_type,
                type_=temp_stage_type,
                postgresql_using=f"stage::text::{temp_enum_name}",
                existing_nullable=False,
            )

        old_stage_type.drop(bind, checkfirst=False)
        new_stage_type.create(bind, checkfirst=False)

        with op.batch_alter_table("lecture_video_processing_runs") as batch_op:
            batch_op.alter_column(
                "stage",
                existing_type=temp_stage_type,
                type_=new_stage_type,
                postgresql_using=f"stage::text::{enum_name}",
                existing_nullable=False,
            )

        temp_stage_type.drop(bind, checkfirst=False)


def downgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            lecture_video_processing_runs_table.delete().where(
                lecture_video_processing_runs_table.c.stage == "MANIFEST_GENERATION"
            )
        )

        temp_stage_type.create(bind, checkfirst=False)

        with op.batch_alter_table("lecture_video_processing_runs") as batch_op:
            batch_op.alter_column(
                "stage",
                existing_type=new_stage_type,
                type_=temp_stage_type,
                postgresql_using=f"stage::text::{temp_enum_name}",
                existing_nullable=False,
            )

        new_stage_type.drop(bind, checkfirst=False)
        old_stage_type.create(bind, checkfirst=False)

        with op.batch_alter_table("lecture_video_processing_runs") as batch_op:
            batch_op.alter_column(
                "stage",
                existing_type=temp_stage_type,
                type_=old_stage_type,
                postgresql_using=f"stage::text::{enum_name}",
                existing_nullable=False,
            )

        temp_stage_type.drop(bind, checkfirst=False)

    op.drop_column("lecture_videos", "manual_manifest")
    op.drop_column("lecture_videos", "generation_prompt")

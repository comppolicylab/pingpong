"""Add lecture generation runtime media

Revision ID: 5d4b8f0c9a12
Revises: 337b7d1fe811
Create Date: 2026-05-29 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5d4b8f0c9a12"
down_revision: Union[str, None] = "337b7d1fe811"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


interaction_enum_name = "interactionmode"
temp_interaction_enum_name = f"temp_{interaction_enum_name}"
old_interaction_values = ("CHAT", "VOICE", "LECTURE_VIDEO")
new_interaction_values = (*old_interaction_values, "LECTURE_GENERATION")
old_interaction_type = sa.Enum(*old_interaction_values, name=interaction_enum_name)
new_interaction_type = sa.Enum(*new_interaction_values, name=interaction_enum_name)
temp_interaction_type = sa.Enum(
    *new_interaction_values, name=temp_interaction_enum_name
)

processing_stage_enum_name = "lecturevideoprocessingstage"
temp_processing_stage_enum_name = f"temp_{processing_stage_enum_name}"
old_processing_stage_values = ("NARRATION", "MANIFEST_GENERATION")
new_processing_stage_values = (
    "NARRATION",
    "MANIFEST_GENERATION",
    "SLIDE_EXTRACTION",
    "LECTURE_GENERATION",
    "HLS_AUDIO",
)
old_processing_stage_type = sa.Enum(
    *old_processing_stage_values, name=processing_stage_enum_name
)
new_processing_stage_type = sa.Enum(
    *new_processing_stage_values, name=processing_stage_enum_name
)
temp_processing_stage_type = sa.Enum(
    *new_processing_stage_values, name=temp_processing_stage_enum_name
)

lecture_video_source_kind_type = sa.Enum(
    "UPLOADED_VIDEO",
    "GENERATED_SLIDE_DECK",
    name="lecturevideosourcekind",
)
lecture_video_playback_kind_type = sa.Enum(
    "VIDEO_FILE",
    "HLS_AUDIO",
    name="lecturevideoplaybackkind",
)
lecture_video_media_role_type = sa.Enum(
    "SOURCE_DECK",
    "SLIDE_IMAGE",
    "HLS_PLAYLIST",
    "HLS_SEGMENT",
    name="lecturevideomediarole",
)

assistants = sa.sql.table(
    "assistants",
    sa.Column("id", sa.Integer()),
    sa.Column("interaction_mode", new_interaction_type),
    sa.Column("lecture_video_id", sa.Integer()),
)
threads = sa.sql.table(
    "threads",
    sa.Column("id", sa.Integer()),
    sa.Column("interaction_mode", new_interaction_type),
    sa.Column("lecture_video_id", sa.Integer()),
)
lecture_videos = sa.sql.table(
    "lecture_videos",
    sa.Column("id", sa.Integer()),
    sa.Column("stored_object_id", sa.Integer()),
    sa.Column("source_kind", lecture_video_source_kind_type),
)
lecture_video_processing_runs = sa.sql.table(
    "lecture_video_processing_runs",
    sa.Column("stage", new_processing_stage_type),
    sa.Column("lecture_video_id", sa.Integer()),
    sa.Column("lecture_video_id_snapshot", sa.Integer()),
)


def _rebuild_interaction_mode_enum(
    *,
    from_type: sa.Enum,
    to_type: sa.Enum,
    temp_type: sa.Enum,
    enum_name: str,
    temp_enum_name: str,
) -> None:
    op.execute("ALTER TABLE assistants ALTER COLUMN interaction_mode DROP DEFAULT")
    op.execute("ALTER TABLE threads ALTER COLUMN interaction_mode DROP DEFAULT")

    bind = op.get_bind()
    temp_type.create(bind, checkfirst=False)

    for table_name in ("assistants", "threads"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "interaction_mode",
                existing_type=from_type,
                type_=temp_type,
                postgresql_using=f"interaction_mode::text::{temp_enum_name}",
                existing_nullable=True,
            )

    from_type.drop(bind, checkfirst=False)
    to_type.create(bind, checkfirst=False)

    for table_name in ("assistants", "threads"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "interaction_mode",
                existing_type=temp_type,
                type_=to_type,
                postgresql_using=f"interaction_mode::text::{enum_name}",
                existing_nullable=True,
            )

    temp_type.drop(bind, checkfirst=False)
    op.execute(
        "ALTER TABLE assistants ALTER COLUMN interaction_mode "
        f"SET DEFAULT 'CHAT'::{enum_name}"
    )
    op.execute(
        "ALTER TABLE threads ALTER COLUMN interaction_mode "
        f"SET DEFAULT 'CHAT'::{enum_name}"
    )


def _rebuild_processing_stage_enum(
    *,
    from_type: sa.Enum,
    to_type: sa.Enum,
    temp_type: sa.Enum,
    enum_name: str,
    temp_enum_name: str,
) -> None:
    bind = op.get_bind()
    temp_type.create(bind, checkfirst=False)

    with op.batch_alter_table("lecture_video_processing_runs") as batch_op:
        batch_op.alter_column(
            "stage",
            existing_type=from_type,
            type_=temp_type,
            postgresql_using=f"stage::text::{temp_enum_name}",
            existing_nullable=False,
        )

    from_type.drop(bind, checkfirst=False)
    to_type.create(bind, checkfirst=False)

    with op.batch_alter_table("lecture_video_processing_runs") as batch_op:
        batch_op.alter_column(
            "stage",
            existing_type=temp_type,
            type_=to_type,
            postgresql_using=f"stage::text::{enum_name}",
            existing_nullable=False,
        )

    temp_type.drop(bind, checkfirst=False)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    if is_postgresql:
        _rebuild_interaction_mode_enum(
            from_type=old_interaction_type,
            to_type=new_interaction_type,
            temp_type=temp_interaction_type,
            enum_name=interaction_enum_name,
            temp_enum_name=temp_interaction_enum_name,
        )
        _rebuild_processing_stage_enum(
            from_type=old_processing_stage_type,
            to_type=new_processing_stage_type,
            temp_type=temp_processing_stage_type,
            enum_name=processing_stage_enum_name,
            temp_enum_name=temp_processing_stage_enum_name,
        )
        lecture_video_source_kind_type.create(bind, checkfirst=True)
        lecture_video_playback_kind_type.create(bind, checkfirst=True)
        lecture_video_media_role_type.create(bind, checkfirst=True)

    op.create_table(
        "lecture_video_media_stored_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=True),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("content_length", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(
        op.f("ix_lecture_video_media_stored_objects_updated"),
        "lecture_video_media_stored_objects",
        ["updated"],
        unique=False,
    )

    op.create_table(
        "lecture_video_media",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecture_video_id", sa.Integer(), nullable=False),
        sa.Column("stored_object_id", sa.Integer(), nullable=False),
        sa.Column("role", lecture_video_media_role_type, nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["lecture_video_id"], ["lecture_videos.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["stored_object_id"],
            ["lecture_video_media_stored_objects.id"],
            name="fk_lecture_video_media_stored_object_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_lecture_video_media_lecture_video_id"),
        "lecture_video_media",
        ["lecture_video_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lecture_video_media_role"),
        "lecture_video_media",
        ["role"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lecture_video_media_stored_object_id"),
        "lecture_video_media",
        ["stored_object_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lecture_video_media_updated"),
        "lecture_video_media",
        ["updated"],
        unique=False,
    )

    with op.batch_alter_table("lecture_videos") as batch_op:
        batch_op.alter_column(
            "stored_object_id",
            existing_type=sa.Integer(),
            nullable=True,
            existing_nullable=False,
        )
        batch_op.add_column(
            sa.Column(
                "source_kind",
                lecture_video_source_kind_type,
                server_default="UPLOADED_VIDEO",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "playback_kind",
                lecture_video_playback_kind_type,
                server_default="VIDEO_FILE",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("source_deck_media_id", sa.Integer()))
        batch_op.add_column(sa.Column("hls_playlist_media_id", sa.Integer()))
        batch_op.add_column(sa.Column("duration_ms", sa.Integer()))
        batch_op.create_foreign_key(
            "fk_lecture_videos_source_deck_media_id",
            "lecture_video_media",
            ["source_deck_media_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_lecture_videos_hls_playlist_media_id",
            "lecture_video_media",
            ["hls_playlist_media_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "lecture_video_slides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecture_video_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("image_media_id", sa.Integer(), nullable=False),
        sa.Column("source_page_number", sa.Integer(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("speaker_notes", sa.Text(), nullable=True),
        sa.Column("narration_text", sa.Text(), nullable=True),
        sa.Column("start_offset_ms", sa.Integer(), nullable=True),
        sa.Column("end_offset_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["image_media_id"],
            ["lecture_video_media.id"],
            name="fk_lecture_video_slides_image_media_id",
        ),
        sa.ForeignKeyConstraint(
            ["lecture_video_id"], ["lecture_videos.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "lecture_video_slide_position_idx",
        "lecture_video_slides",
        ["lecture_video_id", "position"],
        unique=True,
    )
    op.create_index(
        op.f("ix_lecture_video_slides_updated"),
        "lecture_video_slides",
        ["updated"],
        unique=False,
    )


def downgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    op.execute(
        lecture_video_processing_runs.delete().where(
            lecture_video_processing_runs.c.stage.in_(
                ("SLIDE_EXTRACTION", "LECTURE_GENERATION", "HLS_AUDIO")
            )
        )
    )
    op.execute(
        threads.delete().where(threads.c.interaction_mode == "LECTURE_GENERATION")
    )
    op.execute(
        assistants.delete().where(assistants.c.interaction_mode == "LECTURE_GENERATION")
    )

    generated_lecture_video_ids = sa.select(lecture_videos.c.id).where(
        sa.or_(
            lecture_videos.c.source_kind == "GENERATED_SLIDE_DECK",
            lecture_videos.c.stored_object_id.is_(None),
        )
    )
    op.execute(
        threads.update()
        .where(threads.c.lecture_video_id.in_(generated_lecture_video_ids))
        .values(lecture_video_id=None)
    )
    op.execute(
        assistants.update()
        .where(assistants.c.lecture_video_id.in_(generated_lecture_video_ids))
        .values(lecture_video_id=None)
    )
    op.execute(
        lecture_video_processing_runs.update()
        .where(
            lecture_video_processing_runs.c.lecture_video_id.in_(
                generated_lecture_video_ids
            )
        )
        .values(lecture_video_id=None)
    )
    op.execute(
        lecture_videos.delete().where(
            lecture_videos.c.id.in_(generated_lecture_video_ids)
        )
    )

    op.drop_index("lecture_video_slide_position_idx", table_name="lecture_video_slides")
    op.drop_index(
        op.f("ix_lecture_video_slides_updated"), table_name="lecture_video_slides"
    )
    op.drop_table("lecture_video_slides")

    with op.batch_alter_table("lecture_videos") as batch_op:
        batch_op.drop_constraint(
            "fk_lecture_videos_hls_playlist_media_id", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_lecture_videos_source_deck_media_id", type_="foreignkey"
        )
        batch_op.drop_column("duration_ms")
        batch_op.drop_column("hls_playlist_media_id")
        batch_op.drop_column("source_deck_media_id")
        batch_op.drop_column("playback_kind")
        batch_op.drop_column("source_kind")
        batch_op.alter_column(
            "stored_object_id",
            existing_type=sa.Integer(),
            nullable=False,
            existing_nullable=True,
        )

    op.drop_index(
        op.f("ix_lecture_video_media_updated"),
        table_name="lecture_video_media",
    )
    op.drop_index(
        op.f("ix_lecture_video_media_stored_object_id"),
        table_name="lecture_video_media",
    )
    op.drop_index(
        op.f("ix_lecture_video_media_role"),
        table_name="lecture_video_media",
    )
    op.drop_index(
        op.f("ix_lecture_video_media_lecture_video_id"),
        table_name="lecture_video_media",
    )
    op.drop_table("lecture_video_media")

    op.drop_index(
        op.f("ix_lecture_video_media_stored_objects_updated"),
        table_name="lecture_video_media_stored_objects",
    )
    op.drop_table("lecture_video_media_stored_objects")

    if is_postgresql:
        _rebuild_processing_stage_enum(
            from_type=new_processing_stage_type,
            to_type=old_processing_stage_type,
            temp_type=temp_processing_stage_type,
            enum_name=processing_stage_enum_name,
            temp_enum_name=temp_processing_stage_enum_name,
        )
        _rebuild_interaction_mode_enum(
            from_type=new_interaction_type,
            to_type=old_interaction_type,
            temp_type=temp_interaction_type,
            enum_name=interaction_enum_name,
            temp_enum_name=temp_interaction_enum_name,
        )
        lecture_video_media_role_type.drop(bind, checkfirst=True)
        lecture_video_playback_kind_type.drop(bind, checkfirst=True)
        lecture_video_source_kind_type.drop(bind, checkfirst=True)

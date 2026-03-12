"""Updates to support Lecture Video Questions feature

Revision ID: 6812f442bbbb
Revises: 4aed51ccae36
Create Date: 2026-03-12 02:53:23.577105

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6812f442bbbb"
down_revision: Union[str, None] = "4aed51ccae36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_lecture_video_class_ids() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE lecture_videos
            SET class_id = (
                SELECT assistants.class_id
                FROM assistants
                WHERE assistants.lecture_video_id = lecture_videos.id
                ORDER BY assistants.id
                LIMIT 1
            )
            WHERE class_id IS NULL
              AND EXISTS (
                SELECT 1
                FROM assistants
                WHERE assistants.lecture_video_id = lecture_videos.id
              )
            """
        )
    )


def _split_shared_lecture_videos_per_assistant() -> None:
    bind = op.get_bind()
    assistant_rows = (
        bind.execute(
            sa.text(
                """
                SELECT id, class_id, lecture_video_id
                FROM assistants
                WHERE lecture_video_id IS NOT NULL
                ORDER BY lecture_video_id, id
                """
            )
        )
        .mappings()
        .all()
    )

    assistants_by_lecture_video: dict[int, list[dict[str, int]]] = {}
    for row in assistant_rows:
        lecture_video_id = row["lecture_video_id"]
        assistants_by_lecture_video.setdefault(lecture_video_id, []).append(row)

    for lecture_video_id, assistants in assistants_by_lecture_video.items():
        if len(assistants) <= 1:
            continue

        source_video = (
            bind.execute(
                sa.text(
                    """
                SELECT class_id, stored_object_id, display_name, status, error_message, uploader_id
                FROM lecture_videos
                WHERE id = :lecture_video_id
                """
                ),
                {"lecture_video_id": lecture_video_id},
            )
            .mappings()
            .one()
        )

        for assistant in assistants[1:]:
            new_lecture_video_id = bind.execute(
                sa.text(
                    """
                    INSERT INTO lecture_videos (
                        class_id,
                        stored_object_id,
                        display_name,
                        status,
                        error_message,
                        uploader_id
                    )
                    VALUES (
                        :class_id,
                        :stored_object_id,
                        :display_name,
                        :status,
                        :error_message,
                        :uploader_id
                    )
                    RETURNING id
                    """
                ),
                {
                    "class_id": assistant["class_id"],
                    "stored_object_id": source_video["stored_object_id"],
                    "display_name": source_video["display_name"],
                    "status": source_video["status"],
                    "error_message": source_video["error_message"],
                    "uploader_id": source_video["uploader_id"],
                },
            ).scalar_one()

            bind.execute(
                sa.text(
                    """
                    UPDATE assistants
                    SET lecture_video_id = :new_lecture_video_id
                    WHERE id = :assistant_id
                    """
                ),
                {
                    "new_lecture_video_id": new_lecture_video_id,
                    "assistant_id": assistant["id"],
                },
            )
            bind.execute(
                sa.text(
                    """
                    UPDATE threads
                    SET lecture_video_id = :new_lecture_video_id
                    WHERE assistant_id = :assistant_id
                      AND lecture_video_id = :old_lecture_video_id
                    """
                ),
                {
                    "new_lecture_video_id": new_lecture_video_id,
                    "assistant_id": assistant["id"],
                    "old_lecture_video_id": lecture_video_id,
                },
            )


def _unsplit_lecture_videos_per_stored_object() -> None:
    bind = op.get_bind()
    lecture_video_rows = (
        bind.execute(
            sa.text(
                """
                SELECT id, stored_object_id
                FROM lecture_videos
                WHERE stored_object_id IS NOT NULL
                ORDER BY stored_object_id, id
                """
            )
        )
        .mappings()
        .all()
    )

    lecture_videos_by_stored_object: dict[int, list[int]] = {}
    for row in lecture_video_rows:
        lecture_videos_by_stored_object.setdefault(row["stored_object_id"], []).append(
            row["id"]
        )

    for lecture_video_ids in lecture_videos_by_stored_object.values():
        if len(lecture_video_ids) <= 1:
            continue

        canonical_lecture_video_id = lecture_video_ids[0]
        duplicate_lecture_video_ids = lecture_video_ids[1:]

        bind.execute(
            sa.text(
                """
                UPDATE assistants
                SET lecture_video_id = :canonical_lecture_video_id
                WHERE lecture_video_id IN :duplicate_lecture_video_ids
                """
            ).bindparams(sa.bindparam("duplicate_lecture_video_ids", expanding=True)),
            {
                "canonical_lecture_video_id": canonical_lecture_video_id,
                "duplicate_lecture_video_ids": duplicate_lecture_video_ids,
            },
        )
        bind.execute(
            sa.text(
                """
                UPDATE threads
                SET lecture_video_id = :canonical_lecture_video_id
                WHERE lecture_video_id IN :duplicate_lecture_video_ids
                """
            ).bindparams(sa.bindparam("duplicate_lecture_video_ids", expanding=True)),
            {
                "canonical_lecture_video_id": canonical_lecture_video_id,
                "duplicate_lecture_video_ids": duplicate_lecture_video_ids,
            },
        )
        bind.execute(
            sa.text(
                """
                DELETE FROM lecture_videos
                WHERE id IN :duplicate_lecture_video_ids
                """
            ).bindparams(sa.bindparam("duplicate_lecture_video_ids", expanding=True)),
            {"duplicate_lecture_video_ids": duplicate_lecture_video_ids},
        )


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "lecture_video_narration_stored_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
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
        op.f("ix_lecture_video_narration_stored_objects_updated"),
        "lecture_video_narration_stored_objects",
        ["updated"],
        unique=False,
    )

    op.create_table(
        "lecture_video_stored_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
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
        op.f("ix_lecture_video_stored_objects_updated"),
        "lecture_video_stored_objects",
        ["updated"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO lecture_video_stored_objects (key, original_filename, content_type, content_length)
        SELECT
            key,
            key,
            CASE
                WHEN lower(key) LIKE '%.webm' THEN 'video/webm'
                ELSE 'video/mp4'
            END,
            0
        FROM lecture_videos
        """
    )

    op.add_column("lecture_videos", sa.Column("class_id", sa.Integer(), nullable=True))
    op.add_column(
        "lecture_videos", sa.Column("stored_object_id", sa.Integer(), nullable=True)
    )
    sa.Enum(
        "UPLOADED", "PROCESSING", "READY", "FAILED", name="lecturevideostatus"
    ).create(op.get_bind())
    op.add_column(
        "lecture_videos",
        sa.Column(
            "status",
            sa.Enum(
                "UPLOADED", "PROCESSING", "READY", "FAILED", name="lecturevideostatus"
            ),
            server_default="READY",
            nullable=False,
        ),
    )
    op.add_column(
        "lecture_videos", sa.Column("error_message", sa.String(), nullable=True)
    )
    op.create_index(
        op.f("ix_lecture_videos_class_id"), "lecture_videos", ["class_id"], unique=False
    )
    op.create_foreign_key(
        "fk_lecture_videos_class_id_class",
        "lecture_videos",
        "classes",
        ["class_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_lecture_videos_stored_object_id_lecture_video_stored_object",
        "lecture_videos",
        "lecture_video_stored_objects",
        ["stored_object_id"],
        ["id"],
    )
    op.execute(
        """
        UPDATE lecture_videos
        SET
            stored_object_id = (
                SELECT lecture_video_stored_objects.id
                FROM lecture_video_stored_objects
                WHERE lecture_video_stored_objects.key = lecture_videos.key
            ),
            status = COALESCE(status, 'READY')
        """
    )
    with op.batch_alter_table("lecture_videos") as batch_op:
        batch_op.alter_column("stored_object_id", nullable=False)
        batch_op.alter_column("status", server_default="UPLOADED")
        batch_op.alter_column("name", new_column_name="display_name")
        batch_op.drop_column("key")

    _split_shared_lecture_videos_per_assistant()
    _backfill_lecture_video_class_ids()

    op.create_unique_constraint(
        "uq_assistants_lecture_video_id", "assistants", ["lecture_video_id"]
    )

    op.create_table(
        "lecture_video_narrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stored_object_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "PROCESSING",
                "READY",
                "FAILED",
                name="lecturevideonarrationstatus",
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["stored_object_id"],
            ["lecture_video_narration_stored_objects.id"],
            name="fk_lv_narrations_stored_object_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_lecture_video_narrations_stored_object_id"),
        "lecture_video_narrations",
        ["stored_object_id"],
        unique=False,
    )

    op.create_table(
        "lecture_video_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecture_video_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "question_type",
            sa.Enum("SINGLE_SELECT", name="lecturevideoquestiontype"),
            nullable=False,
        ),
        sa.Column("question_text", sa.String(), nullable=False),
        sa.Column("intro_text", sa.String(), nullable=False),
        sa.Column("stop_offset_ms", sa.Integer(), nullable=False),
        sa.Column("intro_narration_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["intro_narration_id"],
            ["lecture_video_narrations.id"],
            name="fk_lv_questions_intro_narration_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lecture_video_id"], ["lecture_videos.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("intro_narration_id"),
    )
    op.create_index(
        "lecture_video_question_position_idx",
        "lecture_video_questions",
        ["lecture_video_id", "position"],
        unique=True,
    )

    op.create_table(
        "lecture_video_question_options",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("option_text", sa.String(), nullable=False),
        sa.Column("post_answer_text", sa.String(), nullable=False),
        sa.Column("continue_offset_ms", sa.Integer(), nullable=False),
        sa.Column("post_narration_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["post_narration_id"],
            ["lecture_video_narrations.id"],
            name="fk_lv_question_options_post_narration_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["lecture_video_questions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", "id"),
        sa.UniqueConstraint("post_narration_id"),
    )
    op.create_index(
        "lecture_video_question_option_position_idx",
        "lecture_video_question_options",
        ["question_id", "position"],
        unique=True,
    )

    op.create_table(
        "lecture_video_question_single_select_correct_options",
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("option_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id", "option_id"],
            [
                "lecture_video_question_options.question_id",
                "lecture_video_question_options.id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["lecture_video_questions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("question_id"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("lecture_video_question_single_select_correct_options")

    op.drop_index(
        "lecture_video_question_option_position_idx",
        table_name="lecture_video_question_options",
    )
    op.drop_table("lecture_video_question_options")

    op.drop_index(
        "lecture_video_question_position_idx", table_name="lecture_video_questions"
    )
    op.drop_table("lecture_video_questions")
    sa.Enum("SINGLE_SELECT", name="lecturevideoquestiontype").drop(
        op.get_bind(), checkfirst=True
    )

    op.drop_index(
        op.f("ix_lecture_video_narrations_stored_object_id"),
        table_name="lecture_video_narrations",
    )
    op.drop_table("lecture_video_narrations")
    sa.Enum(
        "PENDING", "PROCESSING", "READY", "FAILED", name="lecturevideonarrationstatus"
    ).drop(op.get_bind(), checkfirst=True)

    op.drop_constraint("uq_assistants_lecture_video_id", "assistants", type_="unique")

    _unsplit_lecture_videos_per_stored_object()

    op.add_column(
        "lecture_videos", sa.Column("key", sa.String(), nullable=True, unique=True)
    )
    op.create_unique_constraint("uq_lecture_videos_key", "lecture_videos", ["key"])
    op.execute(
        """
        UPDATE lecture_videos
        SET key = (
            SELECT lecture_video_stored_objects.key
            FROM lecture_video_stored_objects
            WHERE lecture_video_stored_objects.id = lecture_videos.stored_object_id
        )
        """
    )

    with op.batch_alter_table("lecture_videos") as batch_op:
        batch_op.drop_constraint("fk_lecture_videos_class_id_class", type_="foreignkey")
        batch_op.drop_constraint(
            "fk_lecture_videos_stored_object_id_lecture_video_stored_object",
            type_="foreignkey",
        )
        batch_op.drop_index(op.f("ix_lecture_videos_class_id"))
        batch_op.drop_column("error_message")
        batch_op.drop_column("status")
        batch_op.drop_column("stored_object_id")
        batch_op.drop_column("class_id")
        batch_op.alter_column("key", nullable=False)
        batch_op.alter_column("display_name", new_column_name="name")

    sa.Enum(
        "UPLOADED", "PROCESSING", "READY", "FAILED", name="lecturevideostatus"
    ).drop(op.get_bind(), checkfirst=True)

    op.drop_index(
        op.f("ix_lecture_video_stored_objects_updated"),
        table_name="lecture_video_stored_objects",
    )
    op.drop_table("lecture_video_stored_objects")

    op.drop_index(
        op.f("ix_lecture_video_narration_stored_objects_updated"),
        table_name="lecture_video_narration_stored_objects",
    )
    op.drop_table("lecture_video_narration_stored_objects")
    # ### end Alembic commands ###

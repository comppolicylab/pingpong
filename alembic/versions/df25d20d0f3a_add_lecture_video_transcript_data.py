"""Add lecture video transcript data

Revision ID: df25d20d0f3a
Revises: c1e4f3a8b9d2
Create Date: 2026-04-27 00:00:00.000000

"""

import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "df25d20d0f3a"
down_revision: Union[str, None] = "c1e4f3a8b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100

lecture_videos_table = sa.sql.table(
    "lecture_videos",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("manifest_data", sa.JSON(), nullable=True),
    sa.Column("transcript_data", sa.JSON(), nullable=True),
)

lecture_video_questions_table = sa.sql.table(
    "lecture_video_questions",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("lecture_video_id", sa.Integer(), nullable=False),
    sa.Column("position", sa.Integer(), nullable=False),
    sa.Column("question_type", sa.String(), nullable=False),
    sa.Column("question_text", sa.String(), nullable=False),
    sa.Column("intro_text", sa.String(), nullable=False),
    sa.Column("stop_offset_ms", sa.Integer(), nullable=False),
)

lecture_video_question_options_table = sa.sql.table(
    "lecture_video_question_options",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("question_id", sa.Integer(), nullable=False),
    sa.Column("position", sa.Integer(), nullable=False),
    sa.Column("option_text", sa.String(), nullable=False),
    sa.Column("post_answer_text", sa.String(), nullable=False),
    sa.Column("continue_offset_ms", sa.Integer(), nullable=False),
)

lecture_video_question_correct_options_table = sa.sql.table(
    "lecture_video_question_single_select_correct_options",
    sa.Column("question_id", sa.Integer(), nullable=False),
    sa.Column("option_id", sa.Integer(), nullable=False),
)


def _word_level_transcription_as_v3(words: object) -> list[dict] | None:
    if not isinstance(words, list) or not words:
        return None
    converted = []
    for word in words:
        if not isinstance(word, dict):
            return None
        if "start_offset_ms" in word and "end_offset_ms" in word:
            converted.append(word)
            continue
        if "start" in word and "end" in word:
            converted.append(
                {
                    "id": word.get("id"),
                    "word": word.get("word"),
                    "start_offset_ms": int(round(float(word.get("start", 0)) * 1000)),
                    "end_offset_ms": int(round(float(word.get("end", 0)) * 1000)),
                }
            )
            continue
        return None
    return converted


def _manifest_version_for_split_transcript(manifest_data: dict) -> int | None:
    version = manifest_data.get("version")
    if version in {1, 2, 3}:
        return version
    if "video_descriptions" in manifest_data:
        return 3

    words = manifest_data.get("word_level_transcription")
    if not isinstance(words, list):
        return None
    if any(
        isinstance(word, dict) and "start_offset_ms" in word and "end_offset_ms" in word
        for word in words
    ):
        return 3
    if any(
        isinstance(word, dict) and "start" in word and "end" in word for word in words
    ):
        return 2
    if "questions" in manifest_data:
        return 1
    return None


def _manifest_extras_for_storage(manifest_data: dict) -> dict | None:
    manifest_version = _manifest_version_for_split_transcript(manifest_data)
    if manifest_version is None:
        return None
    stored_manifest = {"version": manifest_version}
    if manifest_version == 3 and "video_descriptions" in manifest_data:
        stored_manifest["video_descriptions"] = manifest_data["video_descriptions"]
    return stored_manifest


def _v2_word_level_transcription_for_downgrade(words: object) -> list[dict] | None:
    if not isinstance(words, list):
        return None
    converted = []
    for word in words:
        if not isinstance(word, dict):
            return None
        if "start" in word and "end" in word:
            converted.append(word)
            continue
        if "start_offset_ms" in word and "end_offset_ms" in word:
            converted.append(
                {
                    "id": word.get("id"),
                    "word": word.get("word"),
                    "start": word.get("start_offset_ms", 0) / 1000,
                    "end": word.get("end_offset_ms", 0) / 1000,
                }
            )
            continue
        return None
    return converted


def _lecture_video_rows_with_manifest_after_id(bind, last_id: int):
    return bind.execute(
        sa.select(lecture_videos_table.c.id, lecture_videos_table.c.manifest_data)
        .where(
            lecture_videos_table.c.manifest_data.is_not(None),
            lecture_videos_table.c.id > last_id,
        )
        .order_by(lecture_videos_table.c.id.asc())
        .limit(_BATCH_SIZE)
    ).all()


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column(
        "lecture_videos",
        sa.Column("transcript_data", sa.JSON(), nullable=True),
    )
    bind = op.get_bind()
    scanned_count = 0
    updated_count = 0
    last_id = 0
    while True:
        rows = _lecture_video_rows_with_manifest_after_id(bind, last_id)
        if not rows:
            break
        for row in rows:
            last_id = row.id
            scanned_count += 1
            manifest_data = row.manifest_data
            if not isinstance(manifest_data, dict):
                continue
            normalized_manifest = _manifest_extras_for_storage(manifest_data)
            if normalized_manifest is None:
                continue
            word_level_transcription = manifest_data.get("word_level_transcription")
            transcript_data_words = _word_level_transcription_as_v3(
                word_level_transcription
            )
            values = {"manifest_data": normalized_manifest}
            if transcript_data_words:
                values["transcript_data"] = {
                    "version": 3,
                    "word_level_transcription": transcript_data_words,
                }
            bind.execute(
                lecture_videos_table.update()
                .where(lecture_videos_table.c.id == row.id)
                .values(**values)
            )
            updated_count += 1
        logger.info(
            "Split lecture video transcript data batch. scanned=%s updated=%s last_id=%s",
            scanned_count,
            updated_count,
            last_id,
        )
    logger.info(
        "Finished splitting lecture video transcript data. scanned=%s updated=%s",
        scanned_count,
        updated_count,
    )


def _manifest_question_type_for_downgrade(question_type: object) -> object:
    if question_type == "SINGLE_SELECT":
        return "single_select"
    return question_type


def _questions_for_manifest_downgrade(bind, lecture_video_id: int) -> list[dict]:
    questions = []
    question_rows = bind.execute(
        sa.select(
            lecture_video_questions_table.c.id,
            lecture_video_questions_table.c.question_type,
            lecture_video_questions_table.c.question_text,
            lecture_video_questions_table.c.intro_text,
            lecture_video_questions_table.c.stop_offset_ms,
        )
        .where(lecture_video_questions_table.c.lecture_video_id == lecture_video_id)
        .order_by(lecture_video_questions_table.c.position.asc())
    ).all()
    for question_row in question_rows:
        correct_option_id = bind.scalar(
            sa.select(lecture_video_question_correct_options_table.c.option_id).where(
                lecture_video_question_correct_options_table.c.question_id
                == question_row.id
            )
        )
        option_rows = bind.execute(
            sa.select(
                lecture_video_question_options_table.c.id,
                lecture_video_question_options_table.c.option_text,
                lecture_video_question_options_table.c.post_answer_text,
                lecture_video_question_options_table.c.continue_offset_ms,
            )
            .where(
                lecture_video_question_options_table.c.question_id == question_row.id
            )
            .order_by(lecture_video_question_options_table.c.position.asc())
        ).all()
        questions.append(
            {
                "type": _manifest_question_type_for_downgrade(
                    question_row.question_type
                ),
                "question_text": question_row.question_text,
                "intro_text": question_row.intro_text,
                "stop_offset_ms": question_row.stop_offset_ms,
                "options": [
                    {
                        "option_text": option_row.option_text,
                        "post_answer_text": option_row.post_answer_text,
                        "continue_offset_ms": option_row.continue_offset_ms,
                        "correct": option_row.id == correct_option_id,
                    }
                    for option_row in option_rows
                ],
            }
        )
    return questions


def downgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(
            lecture_videos_table.c.id,
            lecture_videos_table.c.manifest_data,
            lecture_videos_table.c.transcript_data,
        ).where(lecture_videos_table.c.manifest_data.is_not(None))
    )
    for row in rows:
        manifest_data = row.manifest_data
        transcript_data = row.transcript_data
        if not isinstance(manifest_data, dict):
            continue
        denormalized_manifest = dict(manifest_data)
        denormalized_manifest["questions"] = _questions_for_manifest_downgrade(
            bind, row.id
        )
        word_level_transcription = (
            transcript_data.get("word_level_transcription")
            if isinstance(transcript_data, dict)
            else None
        )
        if word_level_transcription:
            converted_word_level_transcription = (
                _v2_word_level_transcription_for_downgrade(word_level_transcription)
                if denormalized_manifest.get("version") == 2
                else None
            )
            denormalized_manifest["word_level_transcription"] = (
                converted_word_level_transcription or word_level_transcription
            )
        bind.execute(
            lecture_videos_table.update()
            .where(lecture_videos_table.c.id == row.id)
            .values(manifest_data=denormalized_manifest)
        )
    op.drop_column("lecture_videos", "transcript_data")

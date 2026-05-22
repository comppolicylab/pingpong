import pingpong.models as models
from pingpong.lecture_video_service import TRANSCRIPT_DATA_VERSION
from pingpong.migrations import m10_backfill_lecture_video_captions as m10


def test_has_current_transcript_data_accepts_empty_word_transcript() -> None:
    lecture_video = models.LectureVideo(
        transcript_data={
            "version": TRANSCRIPT_DATA_VERSION,
            "word_level_transcription": [],
        }
    )

    assert m10._has_current_transcript_data(lecture_video)


def test_has_current_transcript_data_rejects_missing_word_transcript() -> None:
    lecture_video = models.LectureVideo(
        transcript_data={
            "version": TRANSCRIPT_DATA_VERSION,
        }
    )

    assert not m10._has_current_transcript_data(lecture_video)

from openai.types.audio.transcription_diarized import TranscriptionDiarized

from pingpong.transcription import format_diarized_transcription_txt


def test_format_diarized_transcription_txt_collapses_consecutive_segments() -> None:
    transcription = TranscriptionDiarized.model_validate(
        {
            "duration": 4.0,
            "task": "transcribe",
            "text": "",
            "segments": [
                {
                    "id": "seg_1",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Hello",
                },
                {
                    "id": "seg_2",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 1.0,
                    "end": 2.0,
                    "text": "there",
                },
                {
                    "id": "seg_3",
                    "type": "transcript.text.segment",
                    "speaker": "spk_2",
                    "start": 2.0,
                    "end": 3.0,
                    "text": "Hi",
                },
                {
                    "id": "seg_4",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 3.0,
                    "end": 4.0,
                    "text": "Back",
                },
            ],
        }
    )

    assert (
        format_diarized_transcription_txt(transcription)
        == "Speaker 1 (00:00-00:02)\nHello there\n\n"
        "Speaker 2 (00:02-00:03)\nHi\n\n"
        "Speaker 1 (00:03-00:04)\nBack\n"
    )

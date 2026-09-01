import json
from types import SimpleNamespace

import pingpong.models as models
from pingpong import schemas
from pingpong import elevenlabs_pronunciation
from pingpong.elevenlabs_config import pronunciation_cache


async def test_v3_pronunciation_conversion_is_cached_and_hint_changes_miss_cache(
    db, monkeypatch
):
    async with db.async_session() as session:
        class_ = models.Class(id=1, name="Pronunciation Class", api_key="sk-test")
        assistant = models.Assistant(
            id=1,
            name="Lecture assistant",
            class_id=1,
            creator_id=1,
            interaction_mode=schemas.InteractionMode.LECTURE_SLIDES,
            model="gpt-4o-mini",
            tools="[]",
            version=3,
            elevenlabs_config=schemas.ElevenLabsConfig().model_dump(mode="json"),
        )
        session.add_all([class_, assistant])
        await session.commit()

    requests: list[dict] = []

    class FakeResponses:
        async def parse(self, **kwargs):
            requests.append(kwargs)
            request = json.loads(kwargs["input"])
            pronunciations = []
            for item in request["items"]:
                ipa = {
                    "leed": "liːd",
                    "led": "/lɛd/",
                    "base": "beɪs",
                }[item["authored_spoken"]]
                pronunciations.append(SimpleNamespace(key=item["key"], ipa=ipa))
            return SimpleNamespace(
                output_parsed=SimpleNamespace(pronunciations=pronunciations)
            )

    async def fake_openai_client(_session, _class_id):
        return SimpleNamespace(responses=FakeResponses())

    monkeypatch.setattr(
        elevenlabs_pronunciation,
        "get_openai_client_by_class_id",
        fake_openai_client,
    )

    first = await elevenlabs_pronunciation.speech_texts_for_elevenlabs(
        assistant_id=1,
        component="narration",
        scope="lecture_slide_narration",
        language_code="en",
        items=[
            elevenlabs_pronunciation.SpeechTextItem(
                item_id=10,
                display_text="Please lead, the class.",
                speech_text="Please leed, the class.",
                context="First slide about conducting a class.",
            ),
            elevenlabs_pronunciation.SpeechTextItem(
                item_id=11,
                display_text="We lead together.",
                speech_text="We leed together.",
                context="Second slide about conducting together.",
            ),
            elevenlabs_pronunciation.SpeechTextItem(
                item_id=12,
                display_text="The bass sounded low.",
                speech_text="The base sounded low.",
                context="A sentence about a musical instrument.",
            ),
        ],
    )
    cached = await elevenlabs_pronunciation.speech_texts_for_elevenlabs(
        assistant_id=1,
        component="narration",
        scope="lecture_slide_narration",
        language_code="en",
        items=[
            elevenlabs_pronunciation.SpeechTextItem(
                item_id=20,
                display_text="They lead today.",
                speech_text="They leed today.",
                context="A new sentence with the cached pronunciation.",
            )
        ],
    )
    changed = await elevenlabs_pronunciation.speech_texts_for_elevenlabs(
        assistant_id=1,
        component="narration",
        scope="lecture_slide_narration",
        language_code="en",
        items=[
            elevenlabs_pronunciation.SpeechTextItem(
                item_id=30,
                display_text="The lead pipe.",
                speech_text="The led pipe.",
                context="A sentence about the metal.",
            )
        ],
    )

    assert first == {
        10: "Please /liːd/, the class.",
        11: "We /liːd/ together.",
        12: "The /beɪs/ sounded low.",
    }
    assert cached == {20: "They /liːd/ today."}
    assert changed == {30: "The /lɛd/ pipe."}
    assert len(requests) == 2

    first_request = requests[0]
    assert first_request["model"] == "gpt-5.6-terra"
    assert first_request["reasoning"]["effort"] == "low"
    assert first_request["store"] is False
    request_payload = json.loads(first_request["input"])
    assert request_payload["language_code"] == "en"
    assert request_payload["scope"] == "lecture_slide_narration"
    assert len(request_payload["items"]) == 2
    lead_item = next(
        item for item in request_payload["items"] if item["written"] == "lead"
    )
    assert lead_item["contexts"] == [
        "First slide about conducting a class.",
        "Second slide about conducting together.",
    ]

    async with db.async_session() as session:
        assistant = await models.Assistant.get_by_id(session, 1)
        assert assistant is not None
        assert set(pronunciation_cache(assistant.elevenlabs_config).values()) == {
            "liːd",
            "beɪs",
            "lɛd",
        }

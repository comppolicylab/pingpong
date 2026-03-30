import pytest

from pingpong import models
from pingpong.api_keys import set_as_default_api_key


@pytest.mark.asyncio
async def test_set_as_default_api_key_supports_gemini(db):
    async with db.async_session() as session:
        api_key = models.APIKey(
            api_key="gemini-secret-key-1234",
            provider="gemini",
        )
        session.add(api_key)
        await session.commit()

        await set_as_default_api_key(
            session,
            redacted_key="gemini-s**********1234",
            key_name="Gemini Default",
            provider="gemini",
        )

        refreshed = await models.APIKey.get_by_id(session, api_key.id)
        assert refreshed is not None
        assert refreshed.available_as_default is True
        assert refreshed.name == "Gemini Default"


@pytest.mark.asyncio
async def test_set_as_default_api_key_supports_elevenlabs(db):
    async with db.async_session() as session:
        api_key = models.APIKey(
            api_key="elevenlabs-secret-key-5678",
            provider="elevenlabs",
        )
        session.add(api_key)
        await session.commit()

        await set_as_default_api_key(
            session,
            redacted_key="elevenla**********5678",
            key_name="ElevenLabs Default",
            provider="elevenlabs",
        )

        refreshed = await models.APIKey.get_by_id(session, api_key.id)
        assert refreshed is not None
        assert refreshed.available_as_default is True
        assert refreshed.name == "ElevenLabs Default"


@pytest.mark.asyncio
async def test_set_as_default_api_key_filters_azure_by_endpoint(db):
    async with db.async_session() as session:
        matching_key = models.APIKey(
            api_key="azure-seMATCHING0009999",
            provider="azure",
            endpoint="https://matching-endpoint.example.com",
        )
        non_matching_key = models.APIKey(
            api_key="azure-seDIFFERENT009999",
            provider="azure",
            endpoint="https://other-endpoint.example.com",
        )
        session.add_all([matching_key, non_matching_key])
        await session.commit()

        await set_as_default_api_key(
            session,
            redacted_key="azure-se**********9999",
            key_name="Azure Default",
            provider="azure",
            endpoint="https://matching-endpoint.example.com",
        )

        refreshed_matching = await models.APIKey.get_by_id(session, matching_key.id)
        refreshed_non_matching = await models.APIKey.get_by_id(
            session, non_matching_key.id
        )
        assert refreshed_matching is not None
        assert refreshed_non_matching is not None
        assert refreshed_matching.available_as_default is True
        assert refreshed_matching.name == "Azure Default"
        assert refreshed_non_matching.available_as_default is False


@pytest.mark.asyncio
async def test_set_as_default_api_key_requires_endpoint_for_azure(db):
    async with db.async_session() as session:
        api_key = models.APIKey(
            api_key="azure-secret-key-1234",
            provider="azure",
            endpoint="https://matching-endpoint.example.com",
        )
        session.add(api_key)
        await session.commit()

        with pytest.raises(ValueError, match="Azure endpoint required"):
            await set_as_default_api_key(
                session,
                redacted_key="azure-se**********1234",
                key_name="Azure Default",
                provider="azure",
            )

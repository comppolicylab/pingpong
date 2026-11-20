"""Backend metadata intersected with the configured Gemini credential's inventory."""

from types import SimpleNamespace

from fastapi import HTTPException
from google import genai
from sqlalchemy.ext.asyncio import AsyncSession

from . import gemini, models, schemas
from .model_catalog import ProviderModel, attach_credential_scope, get_model_catalog

# Video-input, text-output models supporting structured generation.
# https://aistudio.google.com/docs/models (reviewed 2026-11-18)
KNOWN_MODELS = {
    "gemini-4-hydrogen": "Gemini 4 Hydrogen",
    "gemini-4-carbon": "Gemini 4 Carbon",
    "gemini-4-neon": "Gemini 4 Neon",
    "gemini-4-argon": "Gemini 4 Argon",
    "gemini-3.8-flash": "Gemini 3.8 Flash",
    "gemini-3.6-flash": "Gemini 3.6 Flash",
    "gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite",
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite",
}


class _GeminiCatalogModels:
    def __init__(self, api_key: str):
        self._api_key = api_key

    async def list(self):
        # Adapt Google's paginated SDK response to the shared catalog contract.
        async with genai.Client(api_key=self._api_key).aio as client:
            pages = await client.models.list()
            inventory = [
                ProviderModel(id=model.name.removeprefix("models/"), owned_by="google")
                async for model in pages
                if model.name and "generateContent" in (model.supported_actions or [])
            ]
        return SimpleNamespace(data=inventory)


async def list_class_generation_models(
    session: AsyncSession, class_id: int
) -> schemas.LectureGenerationModels:
    default = schemas.LectureGenerationModel(
        id=gemini.DEFAULT_LECTURE_GEMINI_MODEL,
        name=KNOWN_MODELS[gemini.DEFAULT_LECTURE_GEMINI_MODEL],
    )
    credential = await models.ClassCredential.get_by_class_id_and_purpose(
        session,
        class_id,
        schemas.ClassCredentialPurpose.LECTURE_VIDEO_MANIFEST_GENERATION,
    )
    if credential is None or credential.api_key_obj is None:
        return schemas.LectureGenerationModels(models=[], default_model=default)
    client = SimpleNamespace(
        models=_GeminiCatalogModels(credential.api_key_obj.api_key),
        base_url="https://generativelanguage.googleapis.com/v1beta/",
    )
    attach_credential_scope(
        client,
        api_key_id=credential.api_key_obj.id,
        provider="gemini",
        api_version="v1beta",
    )
    try:
        inventory = await get_model_catalog(client)
    except genai.errors.APIError as exc:
        raise HTTPException(
            502,
            "We couldn't fetch available Google models. Check the group's Gemini credential and try again.",
        ) from exc
    available_ids = {model.id for model in inventory.models}
    return schemas.LectureGenerationModels(
        models=[
            schemas.LectureGenerationModel(id=model_id, name=name)
            for model_id, name in KNOWN_MODELS.items()
            if model_id in available_ids
        ],
        default_model=default,
    )

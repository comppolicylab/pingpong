import logging


from pingpong import schemas
from pingpong.ai import get_openai_client_by_class_id
from pingpong.config import config
from pingpong.models import Assistant
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def upgrade_assistants_model(
    deprecated_model: str, replacement_model: str
) -> None:
    async with config.db.driver.async_session() as session:
        assistants_to_upgrade = await Assistant.get_by_model(session, deprecated_model)
        if not assistants_to_upgrade:
            logger.info(f"No assistants found with model name {deprecated_model}")
            return

        for assistant in assistants_to_upgrade:
            logger.info(
                f"Upgrading model for assistant {assistant.name} ({assistant.assistant_id}) from {deprecated_model} to {replacement_model}"
            )
            async with session.begin_nested() as session_:
                try:
                    # Update the model on OpenAI
                    await update_model_on_openai(session, assistant, replacement_model)
                    # Update the model in the database
                    assistant.model = replacement_model
                    session.add(assistant)
                except Exception as e:
                    logger.exception(
                        f"Failed to upgrade model for assistant {assistant.assistant_id} from {deprecated_model} to {replacement_model}: {e}"
                    )
                    await session_.rollback()
                    continue

        await session.commit()
        logger.info(
            f"Completed upgrading assistant models from {deprecated_model} to {replacement_model}"
        )


async def update_model_on_openai(
    session: AsyncSession, assistant: Assistant, new_model: str
) -> None:
    oai_client = await get_openai_client_by_class_id(session, assistant.class_id)
    return await oai_client.beta.assistants.update(
        assistant.assistant_id, model=new_model
    )


# Dictionary to hold model information
KNOWN_MODELS: dict[str, schemas.AssistantModelDict] = {
    # ----------------- Latest Models -----------------
    #
    # -----------------   o* Family   -----------------
    "o1": {
        "name": "o1",
        "sort_order": 4,
        "type": "chat",
        "is_new": True,
        "highlight": False,
        "is_latest": True,
        "supports_vision": False,
        "supports_file_search": False,
        "supports_code_interpreter": False,
        "supports_temperature": False,
        "supports_reasoning": True,
        "description": "Reasoning model designed to solve hard problems across domains. Limited capabilities.",
    },
    "o3-mini": {
        "name": "o3 mini",
        "sort_order": 3,
        "type": "chat",
        "is_new": True,
        "highlight": False,
        "is_latest": True,
        "supports_vision": False,
        "supports_file_search": False,
        "supports_code_interpreter": False,
        "supports_temperature": False,
        "supports_reasoning": True,
        "description": "Faster reasoning model particularly good at coding, math, and science. Limited capabilities.",
    },
    #
    # -----------------   gpt-4.5 Family   -----------------
    #
    "gpt-4.5-preview": {
        "name": "GPT-4.5",
        "sort_order": 2,
        "type": "chat",
        "is_new": True,
        "highlight": False,
        "is_latest": True,
        "supports_vision": True,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "Excels at tasks that benefit from creative, open-ended thinking and conversation, such as writing, learning, or exploring new ideas.",
    },
    #
    # -----------------   gpt-4o Family   -----------------
    #
    "gpt-4o": {
        "name": "GPT-4o",
        "sort_order": 0,
        "type": "chat",
        "is_new": False,
        "highlight": True,
        "is_latest": True,
        "supports_vision": True,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "The latest GPT-4o model, suitable for complex, multi-step tasks.",
    },
    "gpt-4o-mini": {
        "name": "GPT-4o mini",
        "sort_order": 1,
        "type": "chat",
        "is_new": False,
        "highlight": False,
        "is_latest": True,
        "supports_vision": True,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "The latest GPT-4o mini model, suitable for fast, lightweight tasks.",
    },
    #
    # -----------------   gpt-4 Family   -----------------
    #
    "gpt-4-turbo": {
        "name": "GPT-4 Turbo",
        "sort_order": 5,
        "type": "chat",
        "is_new": False,
        "highlight": False,
        "is_latest": True,
        "supports_vision": True,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "The latest GPT-4 Turbo model.",
    },
    "gpt-4-turbo-preview": {
        "name": "GPT-4 Turbo preview",
        "sort_order": 6,
        "type": "chat",
        "is_new": False,
        "highlight": False,
        "is_latest": True,
        "supports_vision": False,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "The latest GPT-4 Turbo preview model.",
    },
    #
    # -----------------   gpt-3.5 Family   -----------------
    #
    "gpt-3.5-turbo": {
        "name": "GPT-3.5 Turbo",
        "sort_order": 7,
        "type": "chat",
        "is_new": False,
        "highlight": False,
        "is_latest": True,
        "supports_vision": False,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "The latest GPT-3.5 Turbo model. Choose the more capable GPT-4o mini model instead.",
    },
    # gpt-3.5-turbo equivalent model in Azure
    "gpt-35-turbo": {
        "name": "GPT-3.5 Turbo",
        "sort_order": 7,
        "type": "chat",
        "is_new": False,
        "highlight": False,
        "is_latest": True,
        "supports_vision": False,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "The latest GPT-3.5 Turbo model. Choose the more capable GPT-4o mini model instead.",
    },
    #
    # ----------------- Realtime Models -----------------
    #
    "gpt-4o-realtime-preview": {
        "name": "GPT-4o Realtime",
        "sort_order": 1,
        "type": "voice",
        "is_new": False,
        "highlight": True,
        "is_latest": True,
        "supports_vision": False,
        "supports_file_search": False,
        "supports_code_interpreter": False,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "Model capable of responding to audio and text inputs in real-time.",
    },
    "gpt-4o-mini-realtime-preview": {
        "name": "GPT-4o mini Realtime",
        "sort_order": 1,
        "type": "voice",
        "is_new": False,
        "highlight": False,
        "is_latest": True,
        "supports_vision": False,
        "supports_file_search": False,
        "supports_code_interpreter": False,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "Smaller model capable of responding to audio and text inputs in real-time.",
    },
    #
    # ----------------- Pinned Models -----------------
    #
    # -----------------   o* Family   -----------------
    "o3-mini-2025-01-31": {
        "name": "o3-mini-2025-01-31",
        "sort_order": 9,
        "type": "chat",
        "is_new": True,
        "highlight": False,
        "is_latest": False,
        "supports_vision": False,
        "supports_file_search": False,
        "supports_code_interpreter": False,
        "supports_temperature": False,
        "supports_reasoning": True,
        "description": "o3 mini initial release version. Limited capabilities.",
    },
    "o1-2024-12-17": {
        "name": "o1-2024-12-17",
        "sort_order": 10,
        "type": "chat",
        "is_new": True,
        "highlight": False,
        "is_latest": False,
        "supports_vision": False,
        "supports_file_search": False,
        "supports_code_interpreter": False,
        "supports_temperature": False,
        "supports_reasoning": True,
        "description": "o1 initial release version. Limited capabilities.",
    },
    #
    # -----------------   gpt-4.5 Family   -----------------
    #
    "gpt-4.5-preview-2025-02-27": {
        "name": "gpt-4.5-preview-2025-02-27",
        "sort_order": 8,
        "type": "chat",
        "is_new": True,
        "highlight": False,
        "is_latest": False,
        "supports_vision": True,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-4.5 initial research preview release version.",
    },
    # -----------------   gpt-4o Family   -----------------
    "gpt-4o-2024-11-20": {
        "name": "gpt-4o-2024-11-20",
        "sort_order": 11,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": True,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-4o model snapshot with enhanced creative writing ability.",
    },
    "gpt-4o-2024-08-06": {
        "name": "gpt-4o-2024-08-06",
        "sort_order": 12,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": True,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-4o model snapshot. GPT-4o (Latest) points to this version.",
    },
    "gpt-4o-2024-05-13": {
        "name": "gpt-4o-2024-05-13",
        "sort_order": 14,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": True,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-4o initial release version.",
    },
    "gpt-4o-mini-2024-07-18": {
        "name": "gpt-4o-mini-2024-07-18",
        "sort_order": 13,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": True,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-4o mini initial release version.",
    },
    # -----------------   gpt-4 Family   -----------------
    "gpt-4-turbo-2024-04-09": {
        "name": "gpt-4-turbo-2024-04-09",
        "sort_order": 15,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": True,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-4 Turbo with Vision model.",
    },
    "gpt-4-0125-preview": {
        "name": "gpt-4-0125-preview",
        "sort_order": 16,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": False,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": 'GPT-4 Turbo preview model with a fix for "laziness," where the model doesn\'t complete a task.',
    },
    # Azure model equivalent
    "gpt-4-0125-Preview": {
        "name": "gpt-4-0125-Preview",
        "sort_order": 16,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": False,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": 'GPT-4 Turbo preview model with a fix for "laziness," where the model doesn\'t complete a task.',
    },
    "gpt-4-1106-preview": {
        "name": "gpt-4-1106-preview",
        "sort_order": 17,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": False,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-4 Turbo preview model with improved instruction following, reproducible outputs, and more.",
    },
    # Azure model equivalent
    "gpt-4-1106-Preview": {
        "name": "gpt-4-1106-Preview",
        "sort_order": 17,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": False,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-4 Turbo preview model with improved instruction following, reproducible outputs, and more.",
    },
    # -----------------   gpt-3.5 Family   -----------------
    "gpt-3.5-turbo-0125": {
        "name": "gpt-3.5-turbo-0125",
        "sort_order": 18,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": False,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-3.5 Turbo model with higher accuracy at responding in requested formats.",
    },
    # Azure model equivalent
    "gpt-35-turbo-0125": {
        "name": "gpt-35-turbo-0125",
        "sort_order": 18,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": False,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-3.5 Turbo model with higher accuracy at responding in requested formats.",
    },
    "gpt-3.5-turbo-1106": {
        "name": "gpt-3.5-turbo-1106",
        "sort_order": 19,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": False,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-3.5 Turbo model with improved instruction following, reproducible outputs, and more.",
    },
    # Azure model equivalent
    "gpt-35-turbo-1106": {
        "name": "gpt-35-turbo-1106",
        "sort_order": 19,
        "type": "chat",
        "is_latest": False,
        "is_new": False,
        "highlight": False,
        "supports_vision": False,
        "supports_file_search": True,
        "supports_code_interpreter": True,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-3.5 Turbo model with improved instruction following, reproducible outputs, and more.",
    },
    #
    # ----------------- Realtime Models -----------------
    #
    "gpt-4o-realtime-preview-2024-12-17": {
        "name": "gpt-4o-realtime-preview-2024-12-17",
        "sort_order": 1,
        "type": "voice",
        "is_new": False,
        "highlight": False,
        "is_latest": False,
        "supports_vision": False,
        "supports_file_search": False,
        "supports_code_interpreter": False,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "Higher intelligence version of the GPT-4o Realtime model. gpt-4o-realtime-preview points to this version.",
    },
    "gpt-4o-realtime-preview-2024-10-01": {
        "name": "gpt-4o-realtime-preview-2024-10-01",
        "sort_order": 2,
        "type": "voice",
        "is_new": False,
        "highlight": False,
        "is_latest": False,
        "supports_vision": False,
        "supports_file_search": False,
        "supports_code_interpreter": False,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-4o Realtime initial release version.",
    },
    "gpt-4o-mini-realtime-preview-2024-12-17": {
        "name": "gpt-4o-mini-realtime-preview-2024-12-17",
        "sort_order": 3,
        "type": "voice",
        "is_new": False,
        "highlight": False,
        "is_latest": False,
        "supports_vision": False,
        "supports_file_search": False,
        "supports_code_interpreter": False,
        "supports_temperature": True,
        "supports_reasoning": False,
        "description": "GPT-4o mini Realtime initial release version.",
    },
    #
}

# Models that should be hidden from the Model Selector
# but are still available for use in existing assistants
# Users should not be able to select these models.
HIDDEN_MODELS = [
    "gpt-4-turbo",
    "gpt-4-turbo-preview",
    "gpt-3.5-turbo",
    "gpt-35-turbo",
    "gpt-4o-2024-05-13",
    "gpt-4-turbo-2024-04-09",
    "gpt-4-0125-preview",
    "gpt-4-0125-Preview",
    "gpt-4-1106-preview",
    "gpt-4-1106-Preview",
    "gpt-3.5-turbo-0125",
    "gpt-35-turbo-0125",
    "gpt-3.5-turbo-1106",
    "gpt-35-turbo-1106",
]

# Models that are only available to admins
# and should not be visible to regular users.
ADMIN_ONLY_MODELS = [
    "gpt-4.5-preview",
    "gpt-4.5-preview-2025-02-27",
]


# Models that are not available in Azure
# and should not be visible to Azure users.
# These models are only available for OpenAI users.
AZURE_UNAVAILABLE_MODELS = [
    "gpt-4o-2024-11-20",
    "o1-2024-12-17",
    "o3-mini",
    "o3-mini-2025-01-31",
    "o1",
    "o1-2024-12-17",
    "gpt-4.5-preview",
    "gpt-4.5-preview-2025-02-27",
    "gpt-4o-realtime-preview",
    "gpt-4o-mini-realtime-preview",
    "gpt-4o-realtime-preview-2024-12-17",
    "gpt-4o-realtime-preview-2024-10-01",
    "gpt-4o-mini-realtime-preview-2024-12-17",
]

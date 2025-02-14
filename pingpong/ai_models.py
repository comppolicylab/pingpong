import logging

import openai

from pingpong.ai import GetOpenAIClientException, get_openai_client_by_class_id
from pingpong.config import config
from pingpong.models import Assistant
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

async def upgrade_assistants_model(deprecated_model: str, replacement_model: str) -> None:
    async with config.db.driver.async_session() as session:
        assistants_to_upgrade = await Assistant.get_by_model(session, deprecated_model)
        if not assistants_to_upgrade:
            logger.info(f"No assistants found with model name {deprecated_model}")
            return

        for assistant in assistants_to_upgrade:
            logger.info(f"Upgrading model for assistant {assistant.name} ({assistant.assistant_id}) from {deprecated_model} to {replacement_model}")
            async with session.begin_nested() as session_:
                try:
                    # Update the model on OpenAI
                    await update_model_on_openai(session, assistant, replacement_model)
                    # Update the model in the database
                    assistant.model = replacement_model
                    session.add(assistant)
                except Exception as e:
                    logger.exception(f"Failed to upgrade model for assistant {assistant.assistant_id} from {deprecated_model} to {replacement_model}: {e}")
                    await session_.rollback()
                    continue


async def update_model_on_openai(session: AsyncSession, assistant: Assistant, new_model: str) -> None:
    oai_client = await get_openai_client_by_class_id(session, assistant.class_id)
    return await oai_client.beta.assistants.update(assistant.assistant_id, model=new_model)

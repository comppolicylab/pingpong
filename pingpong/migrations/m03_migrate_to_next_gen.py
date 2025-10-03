import pingpong.models as models
from pingpong.schemas import InteractionMode
from sqlalchemy.ext.asyncio import AsyncSession

import logging

logger = logging.getLogger(__name__)


async def migrate_to_next_gen(session: AsyncSession) -> None:
    async for (
        assistant
    ) in models.Assistant.get_all_openai_assistants_by_version_and_interaction_mode(
        session, version=2, interaction_mode=InteractionMode.CHAT
    ):
        logger.info(
            f"Migrating assistant to next-gen... ID: {assistant.id}, Name: {assistant.name}, Interaction Mode: {assistant.interaction_mode}, Version: {assistant.version}, Class ID: {assistant.class_id}"
        )
        assistant.version = 3
        session.add(assistant)
        await session.flush()

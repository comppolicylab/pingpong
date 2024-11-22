import aiohttp
from sqlalchemy import and_, select
import pingpong.models as models
from sqlalchemy.ext.asyncio import AsyncSession
import logging

logger = logging.getLogger(__name__)


async def transfer_api_keys(
    session: AsyncSession,
) -> None:
    """
    Transfer API keys from the Class to the APIKey table.

    Args:
        session (AsyncSession): SQLAlchemy session
    """

    stmt = select(models.Class).where(
        and_(
            models.Class.api_key_id is None,
            models.Class.api_key is not None,
        )
    )
    result = await session.execute(stmt)
    for row in result:
        class_ = row[0]
        api_key_obj = await models.APIKey.create_or_update(
            session=session,
            api_key=class_.api_key,
            provider="openai",
        )
        class_.api_key_id = api_key_obj.id
        session.add(class_)

    await session.commit()


async def update_old_api_keys_by_redacted_api_key(
    cls, session: AsyncSession, redacted_key: str, new_key: str
) -> None:
    prefix = redacted_key.split("*", 1)[0]
    suffix = redacted_key.rstrip("*").rsplit("*", 1)[-1]

    stmt = select(cls).where(
        and_(
            models.Class.api_key.like(f"{prefix}%"),
            models.Class.api_key.like(f"%{suffix}"),
        )
    )

    result = await session.execute(stmt)
    classes = result.scalars().all()

    if not classes:
        logger.warning(
            f"update_by_redacted_api_key: No class found for the provided redacted API key: {redacted_key}."
        )
    if len(classes) > 1:
        raise ValueError(
            f"Multiple classes found for the given provided API key: {redacted_key}. No updates performed."
        )

    matched_class = classes[0]
    matched_class.api_key = new_key
    await session.flush()

async def update_new_api_keys_by_redacted_api_key(
    cls, session: AsyncSession, redacted_key: str, new_key: str
) -> None:
    prefix = redacted_key.split("*", 1)[0]
    suffix = redacted_key.rstrip("*").rsplit("*", 1)[-1]

    stmt = select(cls).where(
        and_(
            models.APIKey.api_key.like(f"{prefix}%"),
            models.APIKey.api_key.like(f"%{suffix}"),
            models.APIKey.provider == "openai",
        )
    )

    result = await session.execute(stmt)
    api_key_object = result.scalars().all()

    if not api_key_object:
        logger.warning(
            f"update_new_api_keys_by_redacted_api_key: No API key entry found for the provided redacted API key: {redacted_key}."
        )
    if len(api_key_object) > 1:
        raise ValueError(
            f"Multiple API key entries found for the given provided API key: {redacted_key}. No updates performed."
        )

    matched_api_key_object = api_key_object[0]
    matched_api_key_object.api_key = new_key
    await session.flush()

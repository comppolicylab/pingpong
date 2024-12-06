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
            models.Class.api_key.isnot(None),
            models.Class.api_key_id.is_(None),
        )
    )
    result = await session.execute(stmt)
    for row in result:
        class_ = row[0]
        logging.info(f"Transferring API key for class: {class_.id}")
        api_key_obj = await models.APIKey.create_or_update(
            session=session,
            api_key=class_.api_key,
            provider="openai",
        )
        class_.api_key_id = api_key_obj.id
        session.add(class_)

    await session.commit()


async def update_old_api_keys_by_redacted_api_key(
    session: AsyncSession, prefix: str, suffix: str, new_key: str
) -> None:
    stmt = select(models.Class).where(
        and_(
            models.Class.api_key.like(f"{prefix}%"),
            models.Class.api_key.like(f"%{suffix}"),
        )
    )

    result = await session.execute(stmt)

    for class_ in result.scalars().all():
        logger.info(f"Updating API key {prefix}...{suffix} for class {class_.id}.")
        class_.api_key = new_key
        session.add(class_)

    await session.flush()


async def update_new_api_keys_by_redacted_api_key(
    session: AsyncSession, prefix: str, suffix: str, new_key: str
) -> None:
    stmt = select(models.APIKey).where(
        and_(
            models.APIKey.api_key.like(f"{prefix}%"),
            models.APIKey.api_key.like(f"%{suffix}"),
            models.APIKey.provider == "openai",
        )
    )

    result = await session.execute(stmt)
    api_key_object = result.scalars().all()

    if not api_key_object:
        return
    if len(api_key_object) > 1:
        raise ValueError(
            f"Multiple API key entries found for the given provided API key: {prefix}...{suffix}. No updates performed."
        )

    logger.info(f"Updating classes with API object key {prefix}...{suffix}.")

    old_api_key_object = api_key_object[0]

    new_api_object = await models.APIKey.create_or_update(
        session=session,
        api_key=new_key,
        provider="openai",
    )

    stmt_ = select(models.Class).where(models.Class.api_key_id == old_api_key_object.id)
    result_ = await session.execute(stmt_)
    for class_ in result_.scalars().all():
        logger.info(
            f"Updating API object key {prefix}...{suffix} for class {class_.id}."
        )
        class_.api_key_id = new_api_object.id
        session.add(class_)

    await session.flush()


async def get_process_redacted_project_api_keys(
    db_session: AsyncSession, admin_key: str, project_id: str, new_api_key: str
) -> None:
    """
    Fetches and processes all redacted API keys for the specified project by iterating through all pages.
    """
    api_url = f"https://api.openai.com/v1/organization/projects/{project_id}/api_keys"
    headers = {
        "Authorization": f"Bearer {admin_key}",
        "Content-Type": "application/json",
    }

    after = None  # For pagination

    async with aiohttp.ClientSession() as session:
        while True:
            params = {"limit": 100}
            if after:
                params["after"] = after

            async with session.get(api_url, headers=headers, params=params) as response:
                if response.status != 200:
                    raise Exception(
                        f"Failed to fetch API keys: {response.status} - {await response.text()}"
                    )

                data = await response.json()

                for item in data.get("data", []):
                    redacted_key = item.get("redacted_value")
                    if redacted_key:
                        prefix = redacted_key.split("*", 1)[0]
                        suffix = redacted_key.rstrip("*").rsplit("*", 1)[-1]
                        if prefix and suffix:
                            await update_old_api_keys_by_redacted_api_key(
                                db_session, prefix, suffix, new_api_key
                            )
                            await update_new_api_keys_by_redacted_api_key(
                                db_session, prefix, suffix, new_api_key
                            )
                        else:
                            logger.warning(f"Invalid redacted API key: {redacted_key}")

                if not data.get("has_more", False):
                    break

                after = data.get("last_id")

    await db_session.commit()


async def set_as_default_oai_api_key(
    session: AsyncSession, redacted_key: str, name: str
) -> None:
    prefix = redacted_key.split("*", 1)[0]
    suffix = redacted_key.rstrip("*").rsplit("*", 1)[-1]

    stmt = select(models.APIKey).where(
        and_(
            models.APIKey.api_key.like(f"{prefix}%"),
            models.APIKey.api_key.like(f"%{suffix}"),
            models.APIKey.provider == "openai",
        )
    )

    result = await session.execute(stmt)
    api_key_object = result.scalars().all()

    if not api_key_object:
        raise ValueError(
            f"set_as_default_oai_api_key: No API key entry found for the provided redacted API key: {prefix}...{suffix}."
        )
    if len(api_key_object) > 1:
        raise ValueError(
            f"set_as_default_oai_api_key: Multiple API key entries found for the given provided API key: {prefix}...{suffix}. No updates performed."
        )

    matched_api_key_object = api_key_object[0]
    matched_api_key_object.available_as_default = True
    matched_api_key_object.name = name
    await session.commit()


async def set_as_default_azure_api_key(
    session: AsyncSession,
    redacted_key: str,
    key_name: str,
    endpoint: str,
) -> None:
    prefix = redacted_key.split("*", 1)[0]
    suffix = redacted_key.rstrip("*").rsplit("*", 1)[-1]

    stmt = select(models.APIKey).where(
        and_(
            models.APIKey.api_key.like(f"{prefix}%"),
            models.APIKey.api_key.like(f"%{suffix}"),
            models.APIKey.provider == "azure",
            models.APIKey.endpoint == endpoint,
        )
    )

    result = await session.execute(stmt)
    api_key_object = result.scalars().all()

    if not api_key_object:
        raise ValueError(
            f"set_as_default_azure_api_key: No API key entry found for the provided redacted API key: {prefix}...{suffix}."
        )
        return
    if len(api_key_object) > 1:
        raise ValueError(
            f"set_as_default_azure_api_key: Multiple API key entries found for the given provided API key: {prefix}...{suffix}. No updates performed."
        )

    matched_api_key_object = api_key_object[0]
    matched_api_key_object.available_as_default = True
    matched_api_key_object.name = key_name
    await session.commit()

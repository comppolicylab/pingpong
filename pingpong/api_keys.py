from sqlalchemy import and_, select
import pingpong.models as models
from sqlalchemy.ext.asyncio import AsyncSession

async def transfer_api_keys(
    session: AsyncSession,
) -> None:
    """
    Transfer API keys from the Class to the APIKey table.

    Args:
        session (AsyncSession): SQLAlchemy session
    """
    
    stmt = (
        select(models.Class)
        .where(
            and_(
                models.Class.api_key_id is None,
                models.Class.api_key is not None,
            )
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
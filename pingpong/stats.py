import asyncio
from sqlalchemy import func, select
import pingpong.models as models
from pingpong.schemas import Statistics
from sqlalchemy.ext.asyncio import AsyncSession


async def get_statistics(session: AsyncSession) -> Statistics:
    results = await asyncio.gather(
        session.execute(select(func.count()).select_from(models.Institution)),
        session.execute(select(func.count()).select_from(models.Class)),
        session.execute(select(func.count()).select_from(models.User)),
        session.execute(select(func.count()).select_from(models.UserClassRole)),
        session.execute(select(func.count()).select_from(models.Assistant)),
        session.execute(select(func.count()).select_from(models.Thread)),
        session.execute(select(func.count()).select_from(models.File)),
    )

    institutions_count = results[0].scalar_one()
    classes_count = results[1].scalar_one()
    users_count = results[2].scalar_one()
    enrollments_count = results[3].scalar_one()
    assistants_count = results[4].scalar_one()
    threads_count = results[5].scalar_one()
    files_count = results[6].scalar_one()

    # Return the result as a Statistics object
    return Statistics(
        institutions=institutions_count,
        classes=classes_count,
        users=users_count,
        enrollments=enrollments_count,
        assistants=assistants_count,
        threads=threads_count,
        files=files_count,
    )

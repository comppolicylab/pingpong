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


async def get_statistics_by_institution(
    session: AsyncSession, institution_id: int
) -> Statistics:
    inst_id = int(institution_id)

    classes_count_stmt = (
        select(func.count())
        .select_from(models.Class)
        .where(models.Class.institution_id == inst_id)
    )

    users_count_stmt = (
        select(func.count(func.distinct(models.UserClassRole.user_id)))
        .select_from(models.UserClassRole)
        .join(models.Class, models.UserClassRole.class_id == models.Class.id)
        .where(models.Class.institution_id == inst_id)
    )

    enrollments_count_stmt = (
        select(func.count())
        .select_from(models.UserClassRole)
        .join(models.Class, models.UserClassRole.class_id == models.Class.id)
        .where(models.Class.institution_id == inst_id)
    )

    assistants_count_stmt = (
        select(func.count())
        .select_from(models.Assistant)
        .join(models.Class, models.Assistant.class_id == models.Class.id)
        .where(models.Class.institution_id == inst_id)
    )

    threads_count_stmt = (
        select(func.count())
        .select_from(models.Thread)
        .join(models.Class, models.Thread.class_id == models.Class.id)
        .where(models.Class.institution_id == inst_id)
    )

    direct_file_ids_stmt = (
        select(models.File.id)
        .join(models.Class, models.File.class_id == models.Class.id)
        .where(models.Class.institution_id == inst_id)
    )

    associated_file_ids_stmt = (
        select(models.file_class_association.c.file_id)
        .join(
            models.Class,
            models.file_class_association.c.class_id == models.Class.id,
        )
        .where(models.Class.institution_id == inst_id)
    )

    files_union = direct_file_ids_stmt.union(associated_file_ids_stmt).subquery()
    files_count_stmt = select(func.count()).select_from(files_union)

    results = await asyncio.gather(
        session.execute(
            select(func.count())
            .select_from(models.Institution)
            .where(models.Institution.id == inst_id)
        ),
        session.execute(classes_count_stmt),
        session.execute(users_count_stmt),
        session.execute(enrollments_count_stmt),
        session.execute(assistants_count_stmt),
        session.execute(threads_count_stmt),
        session.execute(files_count_stmt),
    )

    institutions_count = results[0].scalar_one()
    classes_count = results[1].scalar_one()
    users_count = results[2].scalar_one()
    enrollments_count = results[3].scalar_one()
    assistants_count = results[4].scalar_one()
    threads_count = results[5].scalar_one()
    files_count = results[6].scalar_one()

    return Statistics(
        institutions=institutions_count,
        classes=classes_count,
        users=users_count,
        enrollments=enrollments_count,
        assistants=assistants_count,
        threads=threads_count,
        files=files_count,
    )

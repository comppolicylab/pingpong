from pingpong.models import File, file_class_association, _get_upsert_stmt

from sqlalchemy.ext.asyncio import AsyncSession


async def migrate_file_class_id_to_assoc_table(session: AsyncSession) -> None:
    async for file in File.get_all_generator(session):
        stmt = (
            _get_upsert_stmt(session)(file_class_association)
            .values(class_id=file.class_id, file_id=file.id)
            .on_conflict_do_nothing(
                index_elements=["file_id", "class_id"],
            )
        )
        await session.execute(stmt)

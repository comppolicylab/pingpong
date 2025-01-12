"""Script to generate fake data for reproducing scaling issues."""

import click
import logging
import asyncio
import secrets
from datetime import datetime, timezone
from sqlalchemy.sql import func

from pingpong.models import Thread, VectorStore, User
from pingpong.config import config
from pingpong.schemas import VectorStoreType

logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    pass


async def _create_thread(
    db, authz, class_id: int, assistant_id: int, parties: list[int]
):
    slug = f"{datetime.now().timestamp()}.{secrets.token_urlsafe(8)}"

    vector_store_uniq_id = f"fake-vs-{slug}"
    vector_store_object_id = await VectorStore.create(
        db,
        {
            "vector_store_id": vector_store_uniq_id,
            "class_id": class_id,
            "type": VectorStoreType.THREAD,
        },
        file_ids=[],
    )

    thread_name = (
        f"Scaling test thread {datetime.now(timezone.utc).isoformat()} - {slug}"
    )

    users = await User.get_all_by_id(db, parties)
    thread_uniq_id = f"fake-thread-{slug}"
    thread = await Thread.create(
        db,
        {
            "name": thread_name,
            "class_id": int(class_id),
            "private": False,
            "users": users,
            "thread_id": thread_uniq_id,
            "assistant_id": assistant_id,
            "vector_store_id": vector_store_object_id,
            "code_interpreter_file_ids": [],
            "image_file_ids": [],
            "tools_available": "[]",
            "version": 2,
            "last_activity": func.now(),
        },
    )
    grants = [
        (f"class:{class_id}", "parent", f"thread:{thread.id}"),
    ] + [(f"user:{p.id}", "party", f"thread:{thread.id}") for p in users]
    await authz.write(grant=grants)


async def _create_threads(n: int, class_id: int, assistant_id: int, parties: list[int]):
    await config.authz.driver.init()

    for i in range(n):
        logger.info(f"Creating thread {i + 1} of {n} ...")
        async with config.db.driver.async_session_with_args(
            pool_pre_ping=True
        )() as db, config.authz.driver.get_client() as authz:
            try:
                await _create_thread(db, authz, class_id, assistant_id, parties)
                await db.commit()
            except Exception as e:
                logger.error(f"Error creating thread: {e}")
                await db.rollback()
                raise e


@cli.command("threads")
@click.option("-n", default=10, help="Number of new threads to generate")
@click.option(
    "--user-id", help="ID of user to assign threads to", type=int, required=True
)
@click.option(
    "--class-id", help="ID of class to assign threads to", type=int, required=True
)
@click.option(
    "--assistant-id",
    help="ID of assistant to assign threads to",
    type=int,
    required=True,
)
def generate_data(*, n: int, user_id: int, class_id: int, assistant_id: int):
    """Generate fake data for reproducing scaling issues."""
    logger.info(
        f"Generating {n} threads for user {user_id} in class {class_id} with assistant {assistant_id}."
    )

    asyncio.run(_create_threads(n, class_id, assistant_id, [user_id]))

    logger.info("Done.")


if __name__ == "__main__":
    cli()

import asyncio
import logging
import webbrowser

import click

import alembic
import alembic.command
import alembic.config

from .ai import get_openai_client
from .auth import encode_auth_token
from .authz.migrate import sync_db_to_openfga
from .config import config
from .migrate import migrate_object
from .models import Base, User, Class, Assistant, Thread

from sqlalchemy import inspect, update

logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    pass


@cli.group("auth")
def auth() -> None:
    pass


@auth.command("make_root")
@click.argument("email")
def make_root(email: str) -> None:
    async def _make_root() -> None:
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            user = await User.get_by_email(session, email)
            async with config.authz.driver.get_client() as c:
                await c.create_root_user(user.id)

            print(f"User {user.id} promoted to root")

    asyncio.run(_make_root())


@auth.command("migrate")
def migrate_authz() -> None:
    async def _migrate() -> None:
        print("Syncing permissions from database to OpenFga ...")
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            async with config.authz.driver.get_client() as c:
                await sync_db_to_openfga(session, c)

        print("Migration finished!")

    asyncio.run(_migrate())


@auth.command("update_model")
def update_model() -> None:
    async def _update_model() -> None:
        await config.authz.driver.init()
        await config.authz.driver.update_model()

    asyncio.run(_update_model())


@auth.command("login")
@click.argument("email")
@click.argument("redirect", default="/")
@click.option("--super-user/--no-super-user", default=False)
def login(email: str, redirect: str, super_user: bool) -> None:
    async def _get_or_create(email) -> int:
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            user = await User.get_by_email(session, email)
            if not user:
                user = User(email=email)
                user.name = input("Name: ").strip()
                user.super_admin = super_user
                session.add(user)
                async with config.authz.driver.get_client() as c:
                    await c.create_root_user(user.id)
                await session.commit()
                await session.refresh(user)
            return user.id

    user_id = asyncio.run(_get_or_create(email))
    tok = encode_auth_token(user_id)
    url = config.url(f"/api/v1/auth?token={tok}&redirect={redirect}")
    print(f"Magic auth link: {url}")

    # Open the URL in the default browser
    webbrowser.open(url)


def _load_alembic(alembic_config="alembic.ini") -> alembic.config.Config:
    """Load the Alembic config."""
    al_cfg = alembic.config.Config(alembic_config)
    # Use the Alembic config from `alembic.ini` but override the URL for the db
    al_cfg.set_main_option("sqlalchemy.url", config.db.driver.sync_uri)
    return al_cfg


@cli.group("db")
def db() -> None:
    pass


@db.command("init")
@click.option("--clean/--no-clean", default=False)
@click.option("--alembic-config", default="alembic.ini")
def db_init(clean, alembic_config: str) -> None:
    async def init_db(drop_first: bool = False) -> bool:
        """Initialize the database.

        Args:
            drop_first: Whether to drop and recreate the database.

        Returns:
            Whether the database was initialized.
        """
        if not await config.db.driver.exists():
            logger.info("Creating a brand new database")
            await config.db.driver.create()
        else:
            logger.info("Database already exists")

        # Check to see if there are any tables in the database.
        # If there are, we won't force initialization unless `clean` is set.
        # This is to prevent accidental data loss.
        # NOTE(jnu): `inspect` only has a sync interface right now so we have
        # to call that instead of an async version.
        engine = config.db.driver.get_sync_engine()
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        blank_slate = not tables
        if blank_slate:
            logger.info("Database is a blank slate (did not find any tables)")
        else:
            logger.info(
                "Database is *not* a blank slate! found tables: %s", ", ".join(tables)
            )
        engine.dispose()

        # Only init the database if we just created it or we're cleaning it
        if drop_first or blank_slate:
            logger.info(
                "Initializing the database tables because %s",
                "it's a blank slate" if blank_slate else "clean was requested",
            )
            await config.db.driver.init(Base, drop_first=drop_first)
            return True
        return False

    did_init = asyncio.run(init_db(drop_first=clean))

    # Stamp the revision as current so that future migrations will work.
    # Only do this if we initialized the database; otherwise the revision
    # should be set already and might be inaccurate if we re-stamp to head.
    # (To update to the latest revision, use `migrate` after calling `init`.)
    if did_init:
        logger.info("Stamping revision as current")
        al_cfg = _load_alembic(alembic_config)
        alembic.command.stamp(al_cfg, "head")
    else:
        logger.info("Database already initialized; not stamping revision")


@db.command("migrate")
@click.argument("revision", default="head")
@click.option("--downgrade", default=False, is_flag=True)
@click.option("--alembic-config", default="alembic.ini")
def db_migrate(revision: str, downgrade: bool, alembic_config: str) -> None:
    al_cfg = _load_alembic(alembic_config)
    # Run the Alembic migration command (either up or down)
    if downgrade:
        logger.info(f"Downgrading to revision {revision}")
        alembic.command.downgrade(al_cfg, revision)
    else:
        logger.info(f"Upgrading to revision {revision}")
        alembic.command.upgrade(al_cfg, revision)


@db.command("set-version")
@click.argument("version")
@click.option("--alembic-config", default="alembic.ini")
def db_set_version(version: str, alembic_config: str) -> None:
    al_cfg = _load_alembic(alembic_config)
    # Run the Alembic upgrade command
    alembic.command.stamp(al_cfg, version)


@db.command("migrate-version-2")
def migrate_version_2() -> None:
    async def _migrate_version_2() -> None:
        print("Migrating assistants ...")
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            print("Setting versions for all old assistants ...")
            stmt = (
                update(Assistant).values(version=1).where(Assistant.version.is_(None))
            )
            await session.execute(stmt)

            print("Setting versions for all old threads ...")
            stmt = update(Thread).values(version=1).where(Thread.version.is_(None))
            await session.execute(stmt)

            print("Migrating ...")
            async for _class in Class.get_all_with_api_key(session):
                # Create a new client for each API key
                openai_client = get_openai_client(_class.api_key)

                # Get all assistants for the class that haven't been migrated
                async for assistant in Assistant.get_by_class_id_and_version(
                    session, class_id=_class.id, version=1
                ):
                    await migrate_object(openai_client, session, assistant, _class.id)

                # Get all threads for the class that haven't been migrated
                async for thread in Thread.get_by_class_id_and_version(
                    session, class_id=_class.id, version=1
                ):
                    await migrate_object(openai_client, session, thread, _class.id)

            print("Committing ...")
            await session.commit()
            print("Done!")

    asyncio.run(_migrate_version_2())


if __name__ == "__main__":
    cli()

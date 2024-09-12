import asyncio
import logging
import webbrowser
import click
import alembic
import alembic.command
import alembic.config

from croniter import croniter
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from .auth import encode_auth_token
from .bg import get_server
from .canvas import canvas_sync_all
from .config import config
from .models import Base, User

from sqlalchemy import inspect

logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    pass


@cli.group("auth")
def auth() -> None:
    pass


@cli.group("lms")
def lms() -> None:
    pass


@auth.command("create_db_schema")
def create_db_schema() -> None:
    async def _make_db_schema() -> None:
        engine = create_async_engine(
            config.db.driver.async_uri,
            echo=True,
            isolation_level="AUTOCOMMIT",
        )
        async with engine.connect() as conn:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS authz"))
        await engine.dispose()

    asyncio.run(_make_db_schema())


@auth.command("make_root")
@click.argument("email")
def make_root(email: str) -> None:
    async def _make_root() -> None:
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            user = await User.get_by_email(session, email)
            if not user:
                user = User(email=email)
            user.super_admin = True
            session.add(user)
            await session.commit()
            await session.refresh(user)

            async with config.authz.driver.get_client() as c:
                await c.create_root_user(user.id)

            print(f"User {user.id} promoted to root")

    asyncio.run(_make_root())


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
    tok = encode_auth_token(str(user_id))
    url = config.url(f"/api/v1/auth?token={tok}&redirect={redirect}")
    print(f"Magic auth link: {url}")

    # Open the URL in the default browser
    webbrowser.open(url)


def _load_alembic(alembic_config="alembic.ini") -> alembic.config.Config:
    """Load the Alembic config."""
    al_cfg = alembic.config.Config(alembic_config)
    # Use the Alembic config from `alembic.ini` but override the URL for the db
    # If pw uses a % there will be an error thrown in the logs, so "escape" it.
    clean_uri = config.db.driver.sync_uri.replace("%", "%%")
    al_cfg.set_main_option("sqlalchemy.url", clean_uri)
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


async def _sync_all() -> None:
    await config.authz.driver.init()
    async with config.db.driver.async_session() as session:
        async with config.authz.driver.get_client() as c:
            for lms in config.lms.lms_instances:
                match lms.type:
                    case "canvas":
                        logger.info(
                            f"Syncing all classes in {lms.tenant}'s {lms.type} instance..."
                        )
                        await canvas_sync_all(session, c, lms)
                    case _:
                        raise NotImplementedError(f"Unsupported LMS type: {lms.type}")


@lms.command("sync-all")
def sync_all() -> None:
    """
    Sync all classes with a linked LMS class.
    """
    asyncio.run(_sync_all())


@lms.command("sync-all-hourly")
@click.option("--crontime", default="0 * * * *")
@click.option("--host", default="localhost")
@click.option("--port", default=8001)
def sync_all_hourly(crontime: str, host: str, port: int) -> None:
    """
    Run the sync-all command in a background server.
    """
    server = get_server(host=host, port=port)

    # Run the Uvicorn server in the background
    with server.run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run_sync_tasks():
            cron_iter = croniter(crontime, datetime.now())
            while True:
                # Calculate the next run time
                # Note that this ensures that the next run time is always in the future
                # so there are no overlaps in the sync tasks
                next_run_time = cron_iter.get_next(datetime)
                wait_time = (next_run_time - datetime.now()).total_seconds()
                logger.info(
                    f"Next sync scheduled at: {next_run_time} (in {wait_time} seconds)"
                )

                # Wait asynchronously until the next run time
                await asyncio.sleep(wait_time)

                # Run the sync task
                try:
                    await _sync_all()
                    logger.info(f"Sync completed successfully at {datetime.now()}")
                except Exception as e:
                    logger.error(f"Error during sync: {e}")

        loop.run_until_complete(run_sync_tasks())


if __name__ == "__main__":
    cli()

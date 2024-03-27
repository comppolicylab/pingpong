import asyncio
import webbrowser

import click

import alembic
import alembic.command
import alembic.config

from .auth import encode_auth_token
from .authz.migrate import sync_db_to_openfga
from .config import config
from .models import Base, User


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
    async def init_db(drop_first: bool = False) -> None:
        if not await config.db.driver.exists():
            await config.db.driver.create()
        await config.db.driver.init(Base, drop_first=drop_first)

    asyncio.run(init_db(drop_first=clean))

    # Stamp the revision as current so that future migrations will work.
    al_cfg = _load_alembic(alembic_config)
    alembic.command.stamp(al_cfg, "head")


@db.command("migrate")
@click.argument("revision", default="head")
@click.option("--alembic-config", default="alembic.ini")
def db_migrate(revision: str, alembic_config: str) -> None:
    al_cfg = _load_alembic(alembic_config)
    # Run the Alembic upgrade command
    alembic.command.upgrade(al_cfg, revision)


@db.command("set-version")
@click.argument("version")
@click.option("--alembic-config", default="alembic.ini")
def db_set_version(version: str, alembic_config: str) -> None:
    al_cfg = _load_alembic(alembic_config)
    # Run the Alembic upgrade command
    alembic.command.stamp(al_cfg, version)


if __name__ == "__main__":
    cli()

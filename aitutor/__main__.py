import asyncio
import webbrowser

import click

from .auth import encode_auth_token
from .config import config
from .db import async_session, init_db
from .models import User


@click.group()
def cli() -> None:
    pass


@cli.group("auth")
def auth() -> None:
    pass


@auth.command("login")
@click.argument("email")
@click.argument("redirect", default="/")
@click.option("--super-user/--no-super-user", default=False)
def login(email: str, redirect: str, super_user: bool) -> None:
    async def _get_or_create(email) -> int:
        async with async_session() as session:
            user = await User.get_by_email(session, email)
            if not user:
                user = User(email=email)
                user.name = input("Name: ").strip()
                user.super_admin = super_user
                session.add(user)
                await session.commit()
                await session.refresh(user)
            return user.id

    user_id = asyncio.run(_get_or_create(email))
    tok = encode_auth_token(user_id)
    url = config.url(f"/api/v1/auth?token={tok}&redirect={redirect}")
    print(f"Magic auth link: {url}")

    # Open the URL in the default browser
    webbrowser.open(url)


@cli.group("db")
def db() -> None:
    pass


@db.command("init")
@click.option("--clean/--no-clean", default=False)
def db_init(clean) -> None:
    asyncio.run(init_db(drop_first=clean))


if __name__ == "__main__":
    cli()

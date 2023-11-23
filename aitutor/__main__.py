import asyncio
import click

from .db import init_db
from .bot import main
from .config import config
from .errors import sentry
from .metrics import metrics
from .search import ensure_search_index, get_analysis_client, get_chroma_client


@click.group()
def cli() -> None:
    pass


@cli.command("run")
def run() -> None:
    with sentry(), metrics():
        main()


@cli.group("chroma")
def chroma() -> None:
    pass


@chroma.command("ingest")
def ingest() -> None:
    di = get_analysis_client(config.di.key, config.di.endpoint)
    cli = get_chroma_client()
    for m in config.models:
        if m.params.type != "chroma":
            continue
        ensure_search_index(cli, di, m.params.collection, m.params.dirs)


@cli.group("auth")
def auth() -> None:
    pass


@auth.command("login")
@click.argument("email")
def login(email: str) -> None:
    print("TODO")


@cli.group("db")
def db() -> None:
    pass


@db.command("init")
@click.argument("clean", default=False)
def db_init(clean) -> None:
    asyncio.run(init_db(drop_first=clean))



if __name__ == "__main__":
    cli()

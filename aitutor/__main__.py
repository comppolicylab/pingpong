import chromadb
import click

from .bot import main
from .config import config
from .errors import sentry
from .metrics import metrics
from .search import ensure_search_index, get_analysis_client


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
    for m in config.models:
        if m.params.type != "chroma":
            continue
        cli = chromadb.PersistentClient()
        ensure_search_index(cli, di, m.params.collection, m.params.dirs)


if __name__ == "__main__":
    cli()

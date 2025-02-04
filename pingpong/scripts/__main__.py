import asyncio
import click
import logging

from datetime import datetime
from pingpong.bg import get_server
from pingpong.now import croner
from pingpong.scripts.airtable.helpers import (
    _process_airtable_class_requests,
    _process_airtable_nonstudy_class_requests,
    _process_external_logins_to_add_non_study,
    _process_students_to_add,
    _process_external_logins_to_add,
)

logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    pass


@cli.command("sync_pingpong_with_airtable")
@click.option("--crontime", default="*/15 * * * *")
@click.option("--host", default="localhost")
@click.option("--port", default=8001)
def sync_pingpong_with_airtable(crontime: str, host: str, port: int) -> None:
    """
    Run the sync-all command in a background server.
    """
    server = get_server(host=host, port=port)

    async def _sync_pingpong_with_airtable():
        async for _ in croner(crontime, logger=logger):
            try:
                await _process_airtable_class_requests()
                await _process_students_to_add()
                await _process_external_logins_to_add()
                await _process_airtable_nonstudy_class_requests()
                await _process_external_logins_to_add_non_study()
                logger.info(f"Sync completed successfully at {datetime.now()}")
            except Exception as e:
                logger.exception(f"Error during sync: {e}")

    # Run the Uvicorn server in the background
    with server.run_in_thread():
        asyncio.run(_sync_pingpong_with_airtable())


if __name__ == "__main__":
    cli()

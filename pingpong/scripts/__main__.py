import asyncio
import click
import logging

from croniter import croniter
from datetime import datetime
from pingpong.bg import get_server
from pingpong.scripts.helpers import (
    _process_airtable_class_requests,
    _process_students_to_add,
)

logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    pass


@cli.command("process_airtable_class_requests")
def process_airtable_class_requests() -> None:
    """
    Process pending Airtable class creation requests.
    """
    asyncio.run(_process_airtable_class_requests())


@cli.command("process_students_to_add")
def process_students_to_add() -> None:
    """
    Process pending Airtable student creation requests.
    """
    asyncio.run(_process_students_to_add())


@cli.command("sync-all-cron")
@click.option("--crontime", default="*/15 * * * *")
@click.option("--host", default="localhost")
@click.option("--port", default=8001)
def sync_all_cron(crontime: str, host: str, port: int) -> None:
    """
    Run the sync-all command in a background server.
    """
    server = get_server(host=host, port=port)

    async def _sync_all_cron():
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
                await _process_airtable_class_requests()
                await _process_students_to_add()
                logger.info(f"Sync completed successfully at {datetime.now()}")
            except Exception as e:
                logger.error(f"Error during sync: {e}")

    # Run the Uvicorn server in the background
    with server.run_in_thread():
        asyncio.run(_sync_all_cron())


if __name__ == "__main__":
    cli()

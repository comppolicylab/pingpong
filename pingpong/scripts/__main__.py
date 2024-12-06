
import asyncio
import logging

import click

from pingpong.scripts.helpers import _process_airtable_class_requests

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

if __name__ == "__main__":
    cli()
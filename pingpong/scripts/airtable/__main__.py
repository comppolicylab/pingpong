import asyncio
import click
import logging

from datetime import datetime
from pingpong.bg import get_server
from pingpong.now import croner
from pingpong.scripts.airtable.helpers import (
    _process_airtable_class_requests,
    _process_students_to_add,
    _process_external_logins_to_add,
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


@cli.command("process_external_logins_to_add")
def process_external_logins_to_add() -> None:
    """
    Process pending Airtable external login creation requests.
    """
    asyncio.run(_process_external_logins_to_add())


if __name__ == "__main__":
    cli()

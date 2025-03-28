import asyncio
import click
import logging

from pingpong.scripts.qualtrics.helpers import (
    process_exams,
)
from pingpong.scripts.qualtrics.vars import QUALTRICS_USER_EMAIL

logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    pass


@cli.command("generate_postassessments")
@click.option(
    "--email", prompt=(QUALTRICS_USER_EMAIL is None), default=QUALTRICS_USER_EMAIL
)
def generate_postassessments(email: str) -> None:
    """
    Create a new postassessment for each course in the Airtable Classes table.
    """
    asyncio.run(process_exams(email))


if __name__ == "__main__":
    cli()

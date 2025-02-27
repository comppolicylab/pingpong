import asyncio
import click
import logging

from pingpong.scripts.airtable.helpers import (
    _process_airtable_class_requests,
    _process_airtable_class_update_requests,
    _process_remove_self_from_classes,
    _process_airtable_nonstudy_class_requests,
    _process_external_logins_to_add_non_study,
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
    logger.info("Processing class creation requests...")
    asyncio.run(_process_airtable_class_requests())
    logger.info("Finished processing class creation requests.")


@cli.command("process_students_to_add")
def process_students_to_add() -> None:
    """
    Process pending Airtable student creation requests.
    """
    logger.info("Processing student creation requests...")
    asyncio.run(_process_students_to_add())
    logger.info("Finished processing student creation requests.")


@cli.command("process_remove_self_from_classes")
def process_remove_self_from_classes() -> None:
    """
    Process pending Airtable remove self from class requests.
    """
    logger.info("Processing remove self from class requests...")
    asyncio.run(_process_remove_self_from_classes())
    logger.info("Finished processing remove self from class requests.")


@cli.command("process_external_logins_to_add")
def process_external_logins_to_add() -> None:
    """
    Process pending Airtable external login creation requests.
    """
    logger.info("Processing external login creation requests...")
    asyncio.run(_process_external_logins_to_add())
    logger.info("Finished processing external login creation requests.")


@cli.command("process_airtable_nonstudy_class_requests")
def process_airtable_nonstudy_class_requests() -> None:
    """
    Process pending Airtable non-study class creation requests.
    """
    logger.info("Processing non-study class creation requests...")
    asyncio.run(_process_airtable_nonstudy_class_requests())
    logger.info("Finished processing non-study class creation requests.")


@cli.command("process_external_logins_to_add_non_study")
def process_external_logins_to_add_non_study() -> None:
    """
    Process pending Airtable external login creation requests for non-study.
    """
    logger.info("Processing external login creation requests for non-study...")
    asyncio.run(_process_external_logins_to_add_non_study())
    logger.info("Finished processing external login creation requests for non-study.")


@cli.command("process_airtable_class_update_requests")
def process_airtable_class_update_requests() -> None:
    """
    Process pending Airtable class update requests.
    """
    logger.info("Processing class update requests...")
    asyncio.run(_process_airtable_class_update_requests())
    logger.info("Finished processing class update requests.")


if __name__ == "__main__":
    cli()

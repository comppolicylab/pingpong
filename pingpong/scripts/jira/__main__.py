
import asyncio
import click
import logging

from pingpong.scripts.jira.helpers import (
    _add_instructors_to_jira,
    _add_instructors_to_project,
    _add_fields_to_instructors,
    _add_course_to_jira,
    _add_course_to_instructor,
    _add_fields_to_entitlements,
)

logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    pass

@cli.command("add_instructors_to_jira")
def add_instructors_to_jira() -> None:
    """
    Add instructors to Jira.
    """
    asyncio.run(_add_instructors_to_jira())

@cli.command("add_instructors_to_project")
def add_instructors_to_project() -> None:
    """
    Add instructors to Jira Project.
    """
    asyncio.run(_add_instructors_to_project())

@cli.command("add_fields_to_instructors")
def add_fields_to_instructors() -> None:
    """
    Add instructors to Jira Project.
    """
    asyncio.run(_add_fields_to_instructors())

@cli.command("add_course_to_jira")
def add_course_to_jira() -> None:
    """
    Add courses to Jira Project.
    """
    asyncio.run(_add_course_to_jira())

@cli.command("add_course_to_instructor")
def add_course_to_instructor() -> None:
    """
    Add courses to instructor.
    """
    asyncio.run(_add_course_to_instructor())

@cli.command("add_fields_to_entitlements")
def add_fields_to_entitlements() -> None:
    """
    Add course fields.
    """
    asyncio.run(_add_fields_to_entitlements())

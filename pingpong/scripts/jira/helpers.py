import logging

import aiohttp
import pingpong.scripts.jira.schemas as scripts_schemas
import pingpong.scripts.jira.server_requests as server_requests

from pingpong.scripts.jira.vars import PINGPONG_URL, JIRA_TOKEN, JIRA_URL, JIRA_CLOUD_ID
from pyairtable.formulas import match

logger = logging.getLogger(__name__)

if not PINGPONG_URL:
    raise ValueError("Missing PingPong URL in environment.")
else:
    _PINGPONG_URL = PINGPONG_URL

if not JIRA_URL:
    raise ValueError("Missing Jira URL in environment.")
else:
    _JIRA_URL = JIRA_URL

if not JIRA_TOKEN:
    raise ValueError("Missing Jira token in environment.")
else:
    _JIRA_TOKEN = JIRA_TOKEN

if not JIRA_CLOUD_ID:
    raise ValueError("Missing Jira Cloud ID in environment.")
else:
    _JIRA_CLOUD_ID = JIRA_CLOUD_ID


async def _add_instructors_to_jira() -> None:
    instructors_to_add = scripts_schemas.Instructor.all(
        formula=match({"Added to Jira": False})
    )

    async with aiohttp.ClientSession() as session:
        for instructor in instructors_to_add:
            try:
                # Add instructor to Jira
                result = await server_requests.add_instructor_to_jira(
                    session,
                    scripts_schemas.AddInstructorRequest(
                        email=instructor.email,
                        displayName=f"{instructor.first_name} {instructor.last_name}",
                    ),
                    _JIRA_URL,
                    _JIRA_TOKEN,
                )
                instructor.jira_account_id = result.accountId
                instructor.jira = True
                instructor.save()
            except Exception as e:
                logger.warning(f"Error processing instructor: {e}")
                continue


async def _add_instructors_to_project() -> None:
    instructors_to_add = scripts_schemas.Instructor.all(
        formula=match({"Added to Jira Project": False})
    )

    async with aiohttp.ClientSession() as session:
        for instructor in instructors_to_add:
            try:
                # Add instructor to Jira
                await server_requests.add_instructor_to_project(
                    session,
                    instructor.jira_account_id,
                    "1",
                    _JIRA_URL,
                    _JIRA_TOKEN,
                )
                instructor.jira_project = True
                instructor.save()
            except Exception as e:
                logger.warning(f"Error processing instructor: {e}")
                continue


async def _add_fields_to_instructors() -> None:
    instructors_to_add = scripts_schemas.Instructor.all(
        formula=match({"Added Jira Fields": False})
    )

    async with aiohttp.ClientSession() as session:
        for instructor in instructors_to_add:
            try:
                # Add instructor fields to Jira
                await server_requests.add_instructor_field_to_jira(
                    session,
                    instructor.jira_account_id,
                    "Airtable Record URL",
                    [instructor.airtable_url],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_instructor_field_to_jira(
                    session,
                    instructor.jira_account_id,
                    "First Name",
                    [instructor.first_name],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_instructor_field_to_jira(
                    session,
                    instructor.jira_account_id,
                    "Last Name",
                    [instructor.last_name],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_instructor_field_to_jira(
                    session,
                    instructor.jira_account_id,
                    "Email",
                    [instructor.email],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_instructor_field_to_jira(
                    session,
                    instructor.jira_account_id,
                    "Airtable RecordID",
                    [instructor.id],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_instructor_field_to_jira(
                    session,
                    instructor.jira_account_id,
                    "Deadline Survey URL",
                    [instructor.deadline_url],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                instructor.jira_fields = True
                instructor.save()
            except Exception as e:
                logger.warning(f"Error processing instructor: {e}")
                continue


async def _add_course_to_jira() -> None:
    classes_to_add = scripts_schemas.AirtableClass.all(
        formula=(
            match({"Added to Jira": False})
            & (
                match({"Status": "Added — Control"})
                | match({"Status": "Added — Treatment"})
            )
        )
    )

    async with aiohttp.ClientSession() as session:
        for class_ in classes_to_add:
            try:
                # Add course to Jira
                id = await server_requests.add_course_to_jira(
                    session,
                    f"({'T' if class_.randomization == 'Treatment' else 'C'}) {class_.name} ({class_.id})",
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                class_.jira = True
                class_.jira_account_id = id
                class_.save()
            except Exception as e:
                logger.warning(f"Error processing class: {e}")
                continue


async def _add_course_to_instructor() -> None:
    classes_to_add = scripts_schemas.AirtableClass.all(
        formula=(match({"Added to Jira": True}) & match({"Added Entitlement": False}))
    )

    async with aiohttp.ClientSession() as session:
        for class_ in classes_to_add:
            try:
                # Add course to instructor
                id = await server_requests.add_course_to_instructor(
                    session,
                    class_.jira_instructor_id[0],
                    class_.jira_account_id,
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                class_.jira_added_entitlement = True
                class_.jira_entitlement = id
                class_.save()
            except Exception as e:
                logger.warning(f"Error processing class: {e}")
                continue


async def _add_fields_to_entitlements() -> None:
    classes_to_add = scripts_schemas.AirtableClass.all(
        formula=(
            match({"Added to Jira": True})
            & match({"Added Entitlement": True})
            & match({"Added Entitlement Fields": False})
        )
    )

    async with aiohttp.ClientSession() as session:
        for class_ in classes_to_add:
            try:
                # Add class fields to Jira
                await server_requests.add_entitlement_field_to_jira(
                    session,
                    class_.jira_entitlement,
                    "Airtable Record URL",
                    [class_.airtable_url],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_entitlement_field_to_jira(
                    session,
                    class_.jira_entitlement,
                    "Randomization",
                    [class_.randomization],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_entitlement_field_to_jira(
                    session,
                    class_.jira_entitlement,
                    "PingPong Class ID",
                    [
                        class_.pingpong_class_id[0]
                        if len(class_.pingpong_class_id) > 0
                        else ""
                    ],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_entitlement_field_to_jira(
                    session,
                    class_.jira_entitlement,
                    "Student Count",
                    [class_.student_count],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_entitlement_field_to_jira(
                    session,
                    class_.jira_entitlement,
                    "Student Survey URL",
                    [class_.student_survey_url],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_entitlement_field_to_jira(
                    session,
                    class_.jira_entitlement,
                    "Start Date",
                    [class_.start_date],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_entitlement_field_to_jira(
                    session,
                    class_.jira_entitlement,
                    "End Date",
                    [class_.end_date],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_entitlement_field_to_jira(
                    session,
                    class_.jira_entitlement,
                    "Class Name",
                    [class_.name],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                await server_requests.add_entitlement_field_to_jira(
                    session,
                    class_.jira_entitlement,
                    "PingPong Class URL",
                    [
                        f"{_PINGPONG_URL}/group/{class_.pingpong_class_id[0]}/manage"
                        if len(class_.pingpong_class_id) > 0
                        else ""
                    ],
                    _JIRA_CLOUD_ID,
                    _JIRA_TOKEN,
                )
                class_.jira_added_ent_fields = True
                class_.save()
            except Exception as e:
                logger.warning(f"Error processing instructor: {e}")
                continue

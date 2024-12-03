import logging

import aiohttp
import pingpong.schemas as schemas
import pingpong.scripts.schemas as scripts_schemas
import pingpong.scripts.server_requests as server_requests

from pingpong.scripts.vars import (
    BILLING_PROVIDERS,
    PINGPONG_COOKIE,
)
from pyairtable.formulas import match

logger = logging.getLogger(__name__)

if not PINGPONG_COOKIE:
    raise ValueError("Missing PingPong cookie in environment.")
else:
    _PINGPONG_COOKIE = PINGPONG_COOKIE


async def get_or_create_institution(
    session, institution_name: str
) -> schemas.Institution:
    selected_institution = None
    institutions = await server_requests.list_institutions(session)
    institution_names = {
        institution.name: institution for institution in institutions.institutions
    }
    if institution_name in institution_names:
        selected_institution = institution_names[institution_name]
    else:
        selected_institution = await server_requests.create_institution(
            session, schemas.CreateInstitution(name=institution_name)
        )
        logger.info(f'Institution "{institution_name}" did not exist, created.')

    if not selected_institution:
        raise Exception("Institution not found or created.")
    return selected_institution


async def create_class(
    session,
    request: scripts_schemas.AirtableClassRequest,
    institution: schemas.Institution,
) -> schemas.Class:
    billing_configuration = BILLING_PROVIDERS.get(request.billing_api_key, None)
    class_data = schemas.CreateClass(
        name=request.class_name,
        term=request.class_term,
        api_key_id=billing_configuration,
    )

    class_ = await server_requests.create_class(session, institution.id, class_data)
    logger.info(f'Class "{class_.name}" created in "{institution.name}".')
    return class_


async def add_moderator(
    session,
    request: scripts_schemas.AirtableClassRequest,
    class_: schemas.Class,
) -> None:
    user_roles = schemas.CreateUserClassRoles(
        roles=[
            schemas.CreateUserClassRole(
                email=request.teacher_email,
                roles=schemas.ClassUserRoles(admin=False, teacher=True, student=False),
            )
        ]
    )
    user_results = await server_requests.add_user_to_class(
        session, class_.id, user_roles
    )
    if len(user_results.results) > 1:
        raise Exception(
            "More than one user was added to the class. This is unexpected."
        )
    elif len(user_results.results) == 0:
        raise Exception("No user was added to the class. This is unexpected.")
    else:
        teacher = user_results.results[0]

    if teacher.error:
        raise Exception(
            f'Error adding teacher "{teacher.email}" to class "{class_.name}": {teacher.error}'
        )

    logging.info(f'Added teacher "{teacher.email}" to class "{class_.name}".')


async def add_assistant(
    session,
    request: scripts_schemas.AirtableClassRequest,
    class_: schemas.Class,
) -> None:
    billing_configuration = BILLING_PROVIDERS.get(request.billing_api_key, None)
    if not billing_configuration:
        raise Exception("No billing configuration found class, so can't add assistant.")
    assistant_tools = []
    if request.code_interpreter:
        assistant_tools.append({"type": "code_interpreter"})
    if request.file_search:
        assistant_tools.append({"type": "file_search"})

    assistant_data = schemas.CreateAssistant(
        name=request.assistant_name,
        code_interpreter_file_ids=[],
        file_search_file_ids=[],
        instructions=request.assistant_instructions,
        description=request.assistant_description,
        model=request.assistant_model,
        temperature=1.0,
        tools=assistant_tools,
        published=request.publish,
        use_latex=request.use_latex,
        hide_prompt=request.hide_prompt,
    )

    assistant = await server_requests.add_assistant_to_class(
        session, class_.id, assistant_data
    )
    logging.info(
        f'Assistant "{assistant.name}" ({assistant.id}) added to class "{class_.name}" ({class_.id}).'
    )


async def process_requests() -> None:
    requests_to_process = scripts_schemas.AirtableClassRequest.all(
        formula=match({"Status": "Ready for Add"})
    )

    async with aiohttp.ClientSession(cookies={"session": _PINGPONG_COOKIE}) as session:
        for request in requests_to_process:
            try:
                institution = await get_or_create_institution(
                    session, request.class_institution
                )
                class_ = await create_class(session, request, institution)
                await add_moderator(session, request, class_)
                if request.assistant_name:
                    await add_assistant(session, request, class_)
                request.status = "Added"
                request.status_notes = f"Class ID: {class_.id}"
                request.save()
            except Exception as e:
                logger.warning(f"Error processing request: {e}")
                request.status = "Error"
                request.status_notes = str(e)
                request.save()
                continue

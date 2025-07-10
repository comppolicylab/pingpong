import logging

import aiohttp
import pingpong.schemas as schemas
import pingpong.scripts.airtable.schemas as scripts_schemas
import pingpong.scripts.airtable.server_requests as server_requests

from pingpong.scripts.airtable.vars import (
    BILLING_PROVIDERS,
    PINGPONG_COOKIE,
    PINGPONG_URL,
)
from pyairtable.formulas import match, AND, NE, Field

logger = logging.getLogger(__name__)

if not PINGPONG_COOKIE:
    raise ValueError("Missing PingPong cookie in environment.")
else:
    _PINGPONG_COOKIE = PINGPONG_COOKIE

if not PINGPONG_URL:
    raise ValueError("Missing PingPong URL in environment.")
else:
    _PINGPONG_URL = PINGPONG_URL


async def get_or_create_institution(
    session, institution_name: str
) -> schemas.Institution:
    selected_institution = None
    institutions = await server_requests.list_institutions(session, _PINGPONG_URL)
    institution_names = {
        institution.name: institution for institution in institutions.institutions
    }
    if institution_name in institution_names:
        selected_institution = institution_names[institution_name]
    else:
        selected_institution = await server_requests.create_institution(
            session, schemas.CreateInstitution(name=institution_name), _PINGPONG_URL
        )
        logger.debug(f'Institution "{institution_name}" did not exist, created.')

    if not selected_institution:
        raise Exception("Institution not found or created.")
    return selected_institution


async def create_class(
    session,
    request: scripts_schemas.PingPongClass,
    institution: schemas.Institution,
) -> schemas.Class:
    billing_configuration = BILLING_PROVIDERS.get(request.billing_api_key, None)
    class_data = schemas.CreateClass(
        name=request.class_name[0],
        term=request.class_term,
        api_key_id=billing_configuration,
    )

    class_ = await server_requests.create_class(
        session, institution.id, class_data, _PINGPONG_URL
    )
    logger.debug(f'Class "{class_.name}" created in "{institution.name}".')
    return class_


async def add_moderator(
    session,
    request: scripts_schemas.PingPongClass,
    class_: schemas.Class,
) -> None:
    user_roles = schemas.CreateUserClassRoles(
        roles=[
            schemas.CreateUserClassRole(
                email=request.teacher_email[0],
                roles=schemas.ClassUserRoles(admin=False, teacher=True, student=False),
            )
        ],
        silent=True,
    )
    user_results = await server_requests.add_user_to_class(
        session, class_.id, user_roles, _PINGPONG_URL
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

    logger.debug(
        f'Added teacher "{teacher.email}" to class "{class_.name}" ({class_.id}).'
    )


async def remove_self_from_class(
    session,
    class_id: int,
) -> None:
    user = await server_requests.get_me(session, _PINGPONG_URL)
    await server_requests.delete_user_from_class(
        session, class_id, user.id, _PINGPONG_URL
    )
    logger.debug(f'Removed {user.email} from class "{class_id}".')


async def add_student(
    session,
    request: scripts_schemas.UserClassRole,
    class_id: str,
) -> None:
    user_roles = schemas.CreateUserClassRoles(
        roles=[
            schemas.CreateUserClassRole(
                email=request.email,
                roles=schemas.ClassUserRoles(admin=False, teacher=False, student=True),
            )
        ],
        silent=False,
    )
    user_results = await server_requests.add_user_to_class(
        session, int(class_id), user_roles, _PINGPONG_URL
    )
    if len(user_results.results) > 1:
        raise Exception(
            "More than one user was added to the class. This is unexpected."
        )
    elif len(user_results.results) == 0:
        raise Exception("No user was added to the class. This is unexpected.")
    else:
        student = user_results.results[0]

    if student.error:
        raise Exception(
            f'Error adding student "{student.email}" to class {class_id}: {student.error}'
        )

    logger.debug(f'Added student "{student.email}" to class {class_id}.')


def compute_assistant_prompt(
    request: scripts_schemas.PingPongClass | scripts_schemas.PingPongClassNonStudy,
    assistant_template: scripts_schemas.AssistantTemplate
    | scripts_schemas.AssistantTemplateNonStudy,
) -> str:
    prompt = assistant_template.prompt_template[0]
    prompt = prompt.replace(
        assistant_template.course_name_code[0], request.class_name[0]
    )

    if "None" in request.class_programming_languages:
        prompt = prompt.replace(assistant_template.prog_lang_sub_code[0], "")
    elif "Any" in request.class_programming_languages:
        programming_languages = request.class_programming_languages.copy()
        programming_prompt = " " + assistant_template.prog_lang_any[0]
        if "Python" in request.class_programming_languages:
            programming_languages.remove("Python")
        programming_languages.remove("Any")
        if len(programming_languages) == 1:
            extra_prompt = assistant_template.prog_lang_single_with_python[0]
            extra_prompt = extra_prompt.replace(
                assistant_template.prog_lang_code_single[0],
                programming_languages[0],
            )
            programming_prompt = programming_prompt + " " + extra_prompt
        elif len(programming_languages) > 1:
            extra_prompt = assistant_template.prog_lang_multi_with_python[0]
            extra_prompt = extra_prompt.replace(
                assistant_template.prog_lang_code_multi_and[0],
                (
                    ", ".join(programming_languages[:-1])
                    + ", and "
                    + programming_languages[-1]
                ),
            )
            extra_prompt = extra_prompt.replace(
                assistant_template.prog_lang_code_multi_or[0],
                (
                    ", ".join(programming_languages[:-1])
                    + ", or "
                    + programming_languages[-1]
                ),
            )
            programming_prompt = programming_prompt + " " + extra_prompt
        prompt = prompt.replace(
            assistant_template.prog_lang_sub_code[0], programming_prompt
        )
    else:
        programming_languages = request.class_programming_languages.copy()
        programming_prompt = " "
        if "Python" in request.class_programming_languages:
            programming_prompt += assistant_template.prog_lang_python[0]
            programming_languages.remove("Python")
            if len(programming_languages) == 1:
                extra_prompt = assistant_template.prog_lang_single_with_python[0]
                extra_prompt = extra_prompt.replace(
                    assistant_template.prog_lang_code_single[0],
                    programming_languages[0],
                )
                programming_prompt = programming_prompt + " " + extra_prompt
            elif len(programming_languages) > 1:
                extra_prompt = assistant_template.prog_lang_multi_with_python[0]
                extra_prompt = extra_prompt.replace(
                    assistant_template.prog_lang_code_multi_and[0],
                    (
                        ", ".join(programming_languages[:-1])
                        + ", and "
                        + programming_languages[-1]
                    ),
                )
                extra_prompt = extra_prompt.replace(
                    assistant_template.prog_lang_code_multi_or[0],
                    (
                        ", ".join(programming_languages[:-1])
                        + ", or "
                        + programming_languages[-1]
                    ),
                )
                programming_prompt = programming_prompt + " " + extra_prompt
        else:
            if len(programming_languages) == 1:
                extra_prompt = assistant_template.prog_lang_single_no_python[0]
                extra_prompt = extra_prompt.replace(
                    assistant_template.prog_lang_code_single[0],
                    programming_languages[0],
                )
                programming_prompt = programming_prompt + extra_prompt
            elif len(programming_languages) > 1:
                extra_prompt = assistant_template.prog_lang_multi_no_python[0]
                extra_prompt = extra_prompt.replace(
                    assistant_template.prog_lang_code_multi_and[0],
                    (
                        ", ".join(programming_languages[:-1])
                        + ", and "
                        + programming_languages[-1]
                    ),
                )
                extra_prompt = extra_prompt.replace(
                    assistant_template.prog_lang_code_multi_or[0],
                    (
                        ", ".join(programming_languages[:-1])
                        + ", or "
                        + programming_languages[-1]
                    ),
                )
                programming_prompt = programming_prompt + extra_prompt
        prompt = prompt.replace(
            assistant_template.prog_lang_sub_code[0], programming_prompt
        )

    return prompt


def compute_model_name(
    request: scripts_schemas.PingPongClass | scripts_schemas.PingPongClassNonStudy,
    assistant_template: scripts_schemas.AssistantTemplate
    | scripts_schemas.AssistantTemplateNonStudy,
) -> str:
    if request.billing_provider == "Azure":
        return assistant_template.model_azure
    elif request.billing_provider == "OAI":
        return assistant_template.model_oai
    raise Exception("No billing provider found.")


async def lock_assistant(
    session,
    assistant: scripts_schemas.PingPongAssistant
    | scripts_schemas.PingPongAssistantNonStudy,
    class_: schemas.Class,
) -> None:
    await server_requests.lock_assistant(
        session, class_.id, assistant.pingpong_id, _PINGPONG_URL
    )
    return


async def add_assistant(
    session,
    assistant_template: scripts_schemas.AssistantTemplate,
    request: scripts_schemas.PingPongClass,
    class_: schemas.Class,
) -> scripts_schemas.PingPongAssistant:
    billing_configuration = BILLING_PROVIDERS.get(request.billing_api_key, None)
    if not billing_configuration:
        raise Exception("No billing configuration found class, so can't add assistant.")
    assistant_tools = []
    if assistant_template.file_search:
        assistant_tools.append({"type": "file_search"})
    if assistant_template.code_interpreter:
        assistant_tools.append({"type": "code_interpreter"})

    assistant_data = scripts_schemas.CreateAssistant(
        name=assistant_template.name,
        code_interpreter_file_ids=[],
        file_search_file_ids=[],
        instructions=compute_assistant_prompt(request, assistant_template),
        description=assistant_template.description,
        model=compute_model_name(request, assistant_template),
        temperature=assistant_template.temperature,
        tools=assistant_tools,
        published=assistant_template.publish,
        use_latex=assistant_template.use_latex,
        hide_prompt=assistant_template.hide_prompt,
    )

    assistant = await server_requests.add_assistant_to_class(
        session, class_.id, assistant_data, _PINGPONG_URL
    )
    pingpong_assistant = scripts_schemas.PingPongAssistant(
        pingpong_id=assistant.id, template=assistant_template
    )
    pingpong_assistant.save()

    logger.debug(
        f'Assistant "{assistant.name}" ({assistant.id}) added to class "{class_.name}" ({class_.id}).'
    )

    await lock_assistant(session, pingpong_assistant, class_)
    logger.debug(f'Assistant "{assistant.name}" ({assistant.id}) successfully locked.')

    return pingpong_assistant


async def update_assistant(
    session,
    assistant: scripts_schemas.PingPongAssistant,
) -> None:
    assistant_tools = []
    if assistant.update_to.file_search:
        assistant_tools.append({"type": "file_search"})
    if assistant.update_to.code_interpreter:
        assistant_tools.append({"type": "code_interpreter"})

    assistant_data = scripts_schemas.UpdateAssistant(
        name=assistant.update_to.name,
        code_interpreter_file_ids=[],
        file_search_file_ids=[],
        instructions=compute_assistant_prompt(assistant.pp_class, assistant.update_to),
        description=assistant.update_to.description,
        model=compute_model_name(assistant.pp_class, assistant.update_to),
        temperature=assistant.update_to.temperature,
        tools=assistant_tools,
        use_latex=assistant.update_to.use_latex,
        hide_prompt=assistant.update_to.hide_prompt,
        use_image_descriptions=assistant.update_to.experimental_vision,
    )

    # logger.info(f'About to update assistant "{assistant.update_to.name}" ({assistant.pingpong_id}) with data: {assistant_data.model_dump_json(indent=2)}')
    pp_assistant = await server_requests.update_assistant(
        session,
        int(assistant.pp_class.pingpong_id),
        assistant.pingpong_id,
        assistant_data,
        _PINGPONG_URL,
    )
    logger.info(
        f'Assistant "{pp_assistant.name}" ({pp_assistant.id}) updated in class "{assistant.pp_class.class_name}" ({assistant.pp_class.pingpong_id}).'
    )

    return None


async def add_assistant_non_study(
    session,
    assistant_template: scripts_schemas.AssistantTemplateNonStudy,
    request: scripts_schemas.PingPongClassNonStudy,
    class_: schemas.Class,
) -> scripts_schemas.PingPongAssistantNonStudy:
    billing_configuration = BILLING_PROVIDERS.get(request.billing_api_key, None)
    if not billing_configuration:
        raise Exception("No billing configuration found class, so can't add assistant.")
    assistant_tools = []
    if assistant_template.file_search:
        assistant_tools.append({"type": "file_search"})
    if assistant_template.code_interpreter:
        assistant_tools.append({"type": "code_interpreter"})

    assistant_data = scripts_schemas.CreateAssistant(
        name=assistant_template.name,
        code_interpreter_file_ids=[],
        file_search_file_ids=[],
        instructions=compute_assistant_prompt(request, assistant_template),
        description=assistant_template.description,
        model=compute_model_name(request, assistant_template),
        temperature=1.0,
        tools=assistant_tools,
        published=assistant_template.publish,
        use_latex=assistant_template.use_latex,
        hide_prompt=assistant_template.hide_prompt,
    )

    assistant = await server_requests.add_assistant_to_class(
        session, class_.id, assistant_data, _PINGPONG_URL
    )
    pingpong_assistant = scripts_schemas.PingPongAssistantNonStudy(
        pingpong_id=assistant.id, template=assistant_template
    )
    pingpong_assistant.save()

    logger.debug(
        f'Assistant "{assistant.name}" ({assistant.id}) added to class "{class_.name}" ({class_.id}).'
    )

    await lock_assistant(session, pingpong_assistant, class_)
    logger.debug(f'Assistant "{assistant.name}" ({assistant.id}) successfully locked.')

    return pingpong_assistant


async def _process_airtable_class_requests() -> None:
    requests_to_process = scripts_schemas.PingPongClass.all(
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
                await remove_self_from_class(session, class_.id)
                if request.assistant_templates:
                    for assistant_template in request.assistant_templates:
                        pingpong_assistant = await add_assistant(
                            session, assistant_template, request, class_
                        )
                        request.pingpong_assistants.append(pingpong_assistant)
                request.pingpong_id = str(class_.id)
                request.status = "Added"
                request.update_status = "Complete"
                request.remove_admin = True
                request.save()
            except Exception as e:
                logger.warning(f"Error processing request: {e}")
                request.status = "Error"
                request.status_notes = str(e)
                request.save()
                continue


async def _process_airtable_nonstudy_class_requests() -> None:
    requests_to_process = scripts_schemas.PingPongClassNonStudy.all(
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
                if request.assistant_templates:
                    for assistant_template in request.assistant_templates:
                        pingpong_assistant = await add_assistant_non_study(
                            session, assistant_template, request, class_
                        )
                        request.pingpong_assistants.append(pingpong_assistant)
                await remove_self_from_class(session, class_.id)
                request.pingpong_id = str(class_.id)
                request.status = "Added"
                request.update_status = "Complete"
                request.remove_admin = True
                request.save()
                formula = (
                    scripts_schemas.ExternalLoginRequestsNonStudy.current_email.eq(
                        request.teacher_email[0]
                    )
                    & scripts_schemas.ExternalLoginRequestsNonStudy.new_email.eq(
                        request.teacher_personal_email[0]
                    )
                )
                external_logins = scripts_schemas.ExternalLoginRequestsNonStudy.all(
                    formula=formula
                )
                if not external_logins:
                    external_login = scripts_schemas.ExternalLoginRequestsNonStudy(
                        current_email=request.teacher_email[0],
                        new_email=request.teacher_personal_email[0],
                        status="Ready to Add",
                        instructor=[
                            scripts_schemas.InstructorNonStudy.from_id(
                                request.teacher_id[0]
                            )
                        ],
                    )
                    external_login.save()
            except Exception as e:
                logger.warning(f"Error processing request: {e}", exc_info=True)
                request.status = "Error"
                request.status_notes = str(e)
                request.save()
                continue


async def _process_students_to_add() -> None:
    students_to_add = scripts_schemas.UserClassRole.all(
        formula=match({"Status": "Add to Class"})
    )

    async with aiohttp.ClientSession(cookies={"session": _PINGPONG_COOKIE}) as session:
        for student in students_to_add:
            try:
                await add_student(session, student, student.class_id[0])
                student.status = "Added"
                student.save()
            except Exception as e:
                logger.warning(f"Error processing student: {e}")
                student.status = "Error"
                student.status_notes = str(e)
                student.save()
                continue


async def _process_external_logins_to_add() -> None:
    external_logins_to_add = scripts_schemas.ExternalLoginRequests.all(
        formula=match({"Status": "Ready to Add"})
    )

    async with aiohttp.ClientSession(cookies={"session": _PINGPONG_COOKIE}) as session:
        for request in external_logins_to_add:
            try:
                user = await server_requests.get_user_by_email(
                    session, request.current_email, _PINGPONG_URL
                )
                await server_requests.add_login_email(
                    session,
                    user.id,
                    request.new_email,
                    _PINGPONG_URL,
                )
                request.status = "Added"
                request.save()
            except Exception as e:
                logger.warning(f"Error processing external login: {e}")
                request.status = "Error"
                request.status_notes = str(e)
                request.save()
                continue


async def _process_external_logins_to_add_non_study() -> None:
    external_logins_to_add = scripts_schemas.ExternalLoginRequestsNonStudy.all(
        formula=match({"Status": "Ready to Add"})
    )

    async with aiohttp.ClientSession(cookies={"session": _PINGPONG_COOKIE}) as session:
        for request in external_logins_to_add:
            try:
                user = await server_requests.get_user_by_email(
                    session, request.current_email, _PINGPONG_URL
                )
                await server_requests.add_login_email(
                    session,
                    user.id,
                    request.new_email,
                    _PINGPONG_URL,
                )
                request.status = "Added"
                request.save()
            except Exception as e:
                logger.warning(f"Error processing external login: {e}")
                request.status = "Error"
                request.status_notes = str(e)
                request.save()
                continue


async def _process_remove_self_from_classes() -> None:
    classes_to_remove_self = scripts_schemas.PingPongClass.all(
        formula=match({"Remove Admin": False})
    )

    async with aiohttp.ClientSession(cookies={"session": _PINGPONG_COOKIE}) as session:
        for class_ in classes_to_remove_self:
            try:
                await remove_self_from_class(session, int(class_.pingpong_id))
                class_.remove_admin = True
                class_.save()
            except Exception as e:
                logger.warning(f"Error processing class: {e}")
                continue


async def _process_airtable_class_update_requests() -> None:
    requests_to_process = scripts_schemas.PingPongAssistant.all(
        formula=AND(match({"Status": "Update"}), NE(Field("Update To Template"), ""))
    )

    async with aiohttp.ClientSession(cookies={"session": _PINGPONG_COOKIE}) as session:
        for request in requests_to_process:
            try:
                if request.update_to:
                    await update_assistant(session, request)
                request.status = "Complete"
                request.template = request.update_to
                request.update_to = None
                request.save()
            except Exception as e:
                logger.warning(f"Error processing request: {e}")
                request.status = "Error"
                request.status_notes = str(e)
                request.save()
                continue

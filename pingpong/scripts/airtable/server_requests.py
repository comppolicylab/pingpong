import pingpong.schemas as schemas
import pingpong.scripts.airtable.schemas as scripts_schemas


async def list_institutions(session, url: str) -> schemas.Institutions:
    async with session.get(f"{url}/api/v1/institutions", raise_for_status=True) as resp:
        response = await resp.json()
        return schemas.Institutions(**response)


async def create_institution(
    session, institution: schemas.CreateInstitution, url: str
) -> schemas.Institution:
    async with session.post(
        f"{url}/api/v1/institution",
        json=institution.model_dump(),
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.Institution(**response)


async def create_class(
    session, institution_id: int, class_data: schemas.CreateClass, url: str
) -> schemas.Class:
    async with session.post(
        f"{url}/api/v1/institution/{institution_id}/class",
        json=class_data.model_dump(),
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.Class(**response)


async def lock_assistant(
    session, class_id: int, assistant_id: int, url: str
) -> schemas.GenericStatus:
    async with session.post(
        f"{url}/api/v1/class/{class_id}/assistant/{assistant_id}/lock",
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.GenericStatus(**response)


async def add_user_to_class(
    session, class_id: int, user_roles: schemas.CreateUserClassRoles, url: str
) -> schemas.CreateUserResults:
    async with session.post(
        f"{url}/api/v1/class/{class_id}/user",
        json=user_roles.model_dump(),
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.CreateUserResults(**response)


async def add_assistant_to_class(
    session, class_id: int, assistant: scripts_schemas.CreateAssistant, url: str
) -> schemas.Assistant:
    async with session.post(
        f"{url}/api/v1/class/{class_id}/assistant",
        json=assistant.model_dump(),
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.Assistant(**response)

async def add_login_email(
    session, emails: schemas.AddEmailToUserRequest, url: str
) -> schemas.GenericStatus:
    async with session.post(
        f"{url}/api/v1/user/add_email",
        json=emails.model_dump(),
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.GenericStatus(**response)

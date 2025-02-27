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


async def update_assistant(
    session,
    class_id: int,
    assistant_id: int,
    assistant: scripts_schemas.UpdateAssistant,
    url: str,
) -> schemas.Assistant:
    async with session.put(
        f"{url}/api/v1/class/{class_id}/assistant/{assistant_id}",
        json=assistant.model_dump(),
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.Assistant(**response)


async def get_user_by_email(session, email: str, url: str) -> schemas.User:
    async with session.get(
        f"{url}/api/v1/user",
        params={"email": email},
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.User(**response)


async def add_login_email(
    session, user_id: int, new_email: str, url: str
) -> schemas.GenericStatus:
    async with session.post(
        f"{url}/api/v1/user/{user_id}/email",
        params={"email": new_email},
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.GenericStatus(**response)


async def delete_user_from_class(
    session, class_id: int, user_id: int, url: str
) -> schemas.GenericStatus:
    async with session.delete(
        f"{url}/api/v1/class/{class_id}/user/{user_id}",
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.GenericStatus(**response)


async def get_me(session, url: str) -> schemas.User:
    async with session.get(
        f"{url}/api/v1/me",
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.User(**response["user"])

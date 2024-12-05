import pingpong.schemas as schemas


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
    session, class_id: int, assistant: schemas.CreateAssistant, url: str
) -> schemas.Assistant:
    async with session.post(
        f"{url}/api/v1/class/{class_id}/assistant",
        json=assistant.model_dump(),
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.Assistant(**response)

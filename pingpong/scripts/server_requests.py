import pingpong.schemas as schemas


async def list_institutions(
    session, host: str = "localhost:5173"
) -> schemas.Institutions:
    async with session.get(
        f"http://{host}/api/v1/institutions", raise_for_status=True
    ) as resp:
        response = await resp.json()
        return schemas.Institutions(**response)


async def create_institution(
    session, institution: schemas.CreateInstitution, host: str = "localhost:5173"
) -> schemas.Institution:
    async with session.post(
        f"http://{host}/api/v1/institution",
        json=institution.model_dump(),
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.Institution(**response)


async def create_class(
    session,
    institution_id: int,
    class_data: schemas.CreateClass,
    host: str = "localhost:5173",
) -> schemas.Class:
    async with session.post(
        f"http://{host}/api/v1/institution/{institution_id}/class",
        json=class_data.model_dump(),
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.Class(**response)


async def add_user_to_class(
    session,
    class_id: int,
    user_roles: schemas.CreateUserClassRoles,
    host: str = "localhost:5173",
) -> schemas.CreateUserResults:
    async with session.post(
        f"http://{host}/api/v1/class/{class_id}/user",
        json=user_roles.model_dump(),
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.CreateUserResults(**response)


async def add_assistant_to_class(
    session,
    class_id: int,
    assistant: schemas.CreateAssistant,
    host: str = "localhost:5173",
) -> schemas.Assistant:
    async with session.post(
        f"http://{host}/api/v1/class/{class_id}/assistant",
        json=assistant.model_dump(),
        raise_for_status=True,
    ) as resp:
        response = await resp.json()
        return schemas.Assistant(**response)

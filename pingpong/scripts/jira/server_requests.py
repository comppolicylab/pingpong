import pingpong.scripts.jira.schemas as scripts_schemas

async def add_instructor_to_jira(
    session, data: scripts_schemas.AddInstructorRequest, url: str, token: str
) -> scripts_schemas.JiraCustomerResponse:
    auth_header = f"Basic {token}"
    async with session.post(
        f"{url}/rest/servicedeskapi/customer",
        raise_for_status=True,
        json=data.model_dump(),
        headers={
            "Authorization": auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-ExperimentalApi": "true",
        },
    ) as resp:
        response = await resp.json()
        return scripts_schemas.JiraCustomerResponse(**response)


async def add_instructor_to_project(
    session, instructor_id: str, service_desk_id: str, url: str, token: str
) -> None:
    auth_header = f"Basic {token}"
    async with session.post(
        f"{url}/rest/servicedeskapi/servicedesk/{service_desk_id}/customer",
        raise_for_status=True,
        json={"accountIds": [instructor_id]},
        headers={
            "Authorization": auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-ExperimentalApi": "opt-in",
        },
    ) as resp:
        if resp.status == 204:
            return None


async def add_instructor_field_to_jira(
    session, instructor_id: str, field_name: str, field_values: list[str], cloudId: str, token: str
) -> scripts_schemas.JiraCustomerResponse:
    auth_header = f"Basic {token}"
    async with session.put(
        f"https://api.atlassian.com/jsm/csm/cloudid/{cloudId}/api/v1/customer/{instructor_id}/details",
        raise_for_status=True,
        params={"fieldName": field_name},
        json={"values": field_values},
        headers={
            "Authorization": auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-ExperimentalApi": "opt-in",
        },
    ) as resp:
        if resp.status == 200:
            return None

async def add_course_to_jira(
    session, course_name: str, cloudId: str, token: str
) -> str:
    auth_header = f"Basic {token}"
    async with session.post(
        f"https://api.atlassian.com/jsm/csm/cloudid/{cloudId}/api/v1/product",
        raise_for_status=True,
        json={"name": course_name},
        headers={
            "Authorization": auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-ExperimentalApi": "opt-in",
        },
    ) as resp:
        response = await resp.json()
        return response.get("id")


async def add_course_to_instructor(
    session, instructor_id: str, course_id: str, cloudId: str, token: str
) -> str:
    auth_header = f"Basic {token}"
    async with session.post(
        f"https://api.atlassian.com/jsm/csm/cloudid/{cloudId}/api/v1/customer/{instructor_id}/entitlement",
        raise_for_status=True,
        json={"productId": course_id},
        headers={
            "Authorization": auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-ExperimentalApi": "opt-in",
        },
    ) as resp:
        response = await resp.json()
        return response.get("id")

async def add_entitlement_field_to_jira(
    session, entitlement_id: str, field_name: str, field_values: list[str], cloudId: str, token: str
) -> scripts_schemas.JiraCustomerResponse:
    auth_header = f"Basic {token}"
    async with session.put(
        f"https://api.atlassian.com/jsm/csm/cloudid/{cloudId}/api/v1/entitlement/{entitlement_id}/details",
        raise_for_status=True,
        params={"fieldName": field_name},
        json={"values": field_values},
        headers={
            "Authorization": auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-ExperimentalApi": "opt-in",
        },
    ) as resp:
        if resp.status == 200:
            return None
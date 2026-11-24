import json

import pytest
from starlette.requests import Request

from pingpong import audit, models
from pingpong.testutil import with_institution, with_user


def logged(caplog, name):
    return [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == name
    ]


def test_client_ip_uses_last_forwarded_entry():
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"198.51.100.1, 203.0.113.7")],
            "client": ("10.0.0.1", 443),
        }
    )
    assert audit.client_ip(request) == "203.0.113.7"


@with_user(123)
@with_institution(1, "Test Institution")
@pytest.mark.parametrize(
    "authz,elevated",
    [
        ({"grants": [("user:123", "can_edit_info", "class:1")]}, True),
        (
            {
                "grants": [
                    ("user:123", "can_edit_info", "class:1"),
                    ("user:123", "teacher", "class:1"),
                ]
            },
            False,
        ),
    ],
    indirect=["authz"],
)
async def test_class_update_is_audited(
    api, db, institution, valid_user_token, authz, elevated, caplog
):
    async with db.async_session() as session:
        session.add(
            models.Class(id=1, name="Class", term="Fall", institution_id=institution.id)
        )
        await session.commit()

    response = api.put(
        "/api/v1/class/1",
        json={"archived": None},
        headers={
            "Authorization": f"Bearer {valid_user_token}",
            "X-Forwarded-For": "198.51.100.1, 203.0.113.7",
        },
    )
    assert response.status_code == 200

    access = logged(caplog, "pingpong.access")
    assert access[-1]["ip"] == "203.0.113.7"
    assert access[-1]["user_id"] == 123
    assert access[-1]["route"] == "/class/{class_id}"
    events = {event["audit"]: event for event in logged(caplog, "pingpong.audit")}
    assert events["class.update"]["outcome"] == "success"
    assert events["class.update"]["target"] == {"class_id": "1"}
    assert ("privilege.elevated" in events) is elevated

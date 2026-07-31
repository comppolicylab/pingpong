from pingpong import models

from .testutil import with_authz, with_institution, with_user


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "institution:11"),
        ("user:456", "can_create_lecture_lessons", "user:456"),
        ("user:789", "can_create_lecture_lessons", "user:999"),
    ]
)
async def test_institution_admin_can_manage_lecture_lesson_access(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        session.add_all(
            [
                models.User(id=456, email="existing@example.edu"),
                models.User(id=789, email="ineffective@example.edu"),
                models.User(id=999, email="target@example.edu"),
            ]
        )
        await session.commit()

    headers = {"Authorization": f"Bearer {valid_user_token}"}
    response = api.get("/api/v1/admin/lecture-lessons/access", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "users": [
            {
                "id": 456,
                "email": "existing@example.edu",
                "first_name": None,
                "last_name": None,
                "display_name": None,
                "name": "existing@example.edu",
                "has_real_name": False,
            }
        ]
    }

    response = api.post(
        "/api/v1/admin/lecture-lessons/access",
        headers=headers,
        json={"email": "new-user@example.edu"},
    )

    assert response.status_code == 200
    added = response.json()
    assert added["email"] == "new-user@example.edu"
    assert added["added_access"] is True

    response = api.post(
        "/api/v1/admin/lecture-lessons/access",
        headers=headers,
        json={"email": "new-user@example.edu"},
    )

    assert response.status_code == 200
    assert response.json()["added_access"] is False

    response = api.get("/api/v1/admin/lecture-lessons/access", headers=headers)

    assert response.status_code == 200
    assert [user["email"] for user in response.json()["users"]] == [
        "existing@example.edu",
        "new-user@example.edu",
    ]

    response = api.delete(
        f"/api/v1/admin/lecture-lessons/access/{added['user_id']}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    response = api.get("/api/v1/admin/lecture-lessons/access", headers=headers)

    assert response.status_code == 200
    assert [user["email"] for user in response.json()["users"]] == [
        "existing@example.edu"
    ]


@with_user(123)
@with_authz(grants=[])
async def test_lecture_lesson_access_management_requires_admin(api, valid_user_token):
    headers = {"Authorization": f"Bearer {valid_user_token}"}

    assert (
        api.get("/api/v1/admin/lecture-lessons/access", headers=headers).status_code
        == 403
    )
    assert (
        api.post(
            "/api/v1/admin/lecture-lessons/access",
            headers=headers,
            json={"email": "user@example.edu"},
        ).status_code
        == 403
    )
    assert (
        api.delete(
            "/api/v1/admin/lecture-lessons/access/456", headers=headers
        ).status_code
        == 403
    )

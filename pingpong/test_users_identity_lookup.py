from types import SimpleNamespace

import pytest

import pingpong.models as models
import pingpong.schemas as schemas
import pingpong.users as users_module
from pingpong.users import AddNewUsersScript


class _FakeAuthzClient:
    async def test(self, *args, **kwargs):
        return True

    async def write_safe(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_lookup_user_prefers_external_logins_over_legacy_sso(monkeypatch):
    new_ucr = schemas.CreateUserClassRoles(
        roles=[],
        sso_tenant="legacy-tenant",
    )
    add_users = AddNewUsersScript(
        class_id="1",
        user_id=1,
        session=SimpleNamespace(),
        client=_FakeAuthzClient(),
        new_ucr=new_ucr,
    )
    ucr = schemas.CreateUserClassRole(
        email="user@example.com",
        sso_id="legacy-id",
        external_logins=[
            schemas.ExternalLoginLookupItem(
                provider="issuer.example.com", identifier="sub-123"
            )
        ],
        roles=schemas.ClassUserRoles(admin=False, teacher=True, student=False),
    )

    captured_lookup_items: list[schemas.ExternalLoginLookupItem] = []

    async def _get_by_email_external_logins_priority(session, email, lookup_items):
        captured_lookup_items.extend(lookup_items)
        return None, []

    monkeypatch.setattr(
        models.User,
        "get_by_email_external_logins_priority",
        _get_by_email_external_logins_priority,
    )

    await add_users._lookup_user_for_ucr(ucr)

    assert len(captured_lookup_items) == 2
    assert captured_lookup_items[0].provider == "issuer.example.com"
    assert captured_lookup_items[0].identifier == "sub-123"
    assert captured_lookup_items[1].provider == "email"
    assert captured_lookup_items[1].identifier == "user@example.com"


@pytest.mark.asyncio
async def test_lookup_user_falls_back_to_legacy_sso_when_external_logins_empty(
    monkeypatch,
):
    new_ucr = schemas.CreateUserClassRoles(
        roles=[],
        sso_tenant="legacy-tenant",
    )
    add_users = AddNewUsersScript(
        class_id="1",
        user_id=1,
        session=SimpleNamespace(),
        client=_FakeAuthzClient(),
        new_ucr=new_ucr,
    )
    ucr = schemas.CreateUserClassRole(
        email="user@example.com",
        sso_id="legacy-id",
        roles=schemas.ClassUserRoles(admin=False, teacher=True, student=False),
    )

    captured_lookup_items: list[schemas.ExternalLoginLookupItem] = []

    async def _get_by_email_external_logins_priority(session, email, lookup_items):
        captured_lookup_items.extend(lookup_items)
        return None, []

    monkeypatch.setattr(
        models.User,
        "get_by_email_external_logins_priority",
        _get_by_email_external_logins_priority,
    )

    await add_users._lookup_user_for_ucr(ucr)

    assert len(captured_lookup_items) == 2
    assert captured_lookup_items[0].provider == "legacy-tenant"
    assert captured_lookup_items[0].identifier == "legacy-id"
    assert captured_lookup_items[1].provider == "email"
    assert captured_lookup_items[1].identifier == "user@example.com"


@pytest.mark.asyncio
async def test_lookup_user_ambiguous_external_login_falls_back_to_email_only(
    monkeypatch,
):
    new_ucr = schemas.CreateUserClassRoles(
        roles=[],
        sso_tenant="legacy-tenant",
    )
    add_users = AddNewUsersScript(
        class_id="1",
        user_id=1,
        session=SimpleNamespace(),
        client=_FakeAuthzClient(),
        new_ucr=new_ucr,
    )
    ucr = schemas.CreateUserClassRole(
        email="user@example.com",
        sso_id="legacy-id",
        external_logins=[
            schemas.ExternalLoginLookupItem(
                provider="issuer.example.com", identifier="sub-123"
            )
        ],
        roles=schemas.ClassUserRoles(admin=False, teacher=True, student=False),
    )

    captured_calls: list[list[schemas.ExternalLoginLookupItem]] = []

    async def _get_by_email_external_logins_priority(session, email, lookup_items):
        captured_calls.append(list(lookup_items))
        if len(captured_calls) == 1:
            raise models.AmbiguousExternalLoginLookupError(
                lookup_index=0,
                lookup_item=lookup_items[0],
                user_ids=[1, 2],
            )
        return None, []

    monkeypatch.setattr(
        models.User,
        "get_by_email_external_logins_priority",
        _get_by_email_external_logins_priority,
    )

    await add_users._lookup_user_for_ucr(ucr)

    assert len(captured_calls) == 2
    assert [i.provider for i in captured_calls[0]] == ["issuer.example.com", "email"]
    assert [i.provider for i in captured_calls[1]] == ["email"]


@pytest.mark.asyncio
async def test_merge_matched_user_ids_deduplicates_old_user_merges(
    monkeypatch,
):
    new_ucr = schemas.CreateUserClassRoles(
        roles=[],
        lms_tenant="canvas-tenant",
    )
    add_users = AddNewUsersScript(
        class_id="1",
        user_id=1,
        session=SimpleNamespace(),
        client=_FakeAuthzClient(),
        new_ucr=new_ucr,
    )
    merge_calls: list[tuple[int, int]] = []

    async def _merge(session, client, new_user_id, old_user_id):
        merge_calls.append((new_user_id, old_user_id))
        return SimpleNamespace(id=new_user_id)

    monkeypatch.setattr(users_module, "merge", _merge)

    canonical_user = SimpleNamespace(id=10)
    merged_old_user_ids = {30}
    result_user = await add_users._merge_matched_user_ids(
        canonical_user,
        [10, 20, 30, 20, 40],
        merged_old_user_ids,
    )

    assert merge_calls == [
        (10, 20),
        (10, 40),
    ]
    assert result_user.id == 10


@pytest.mark.asyncio
async def test_add_new_users_skips_identity_upsert_for_rejected_manual_lms_edit(
    monkeypatch,
):
    new_ucr = schemas.CreateUserClassRoles(
        roles=[
            schemas.CreateUserClassRole(
                email="imported@example.com",
                sso_id="legacy-id",
                roles=schemas.ClassUserRoles(admin=False, teacher=True, student=False),
            )
        ],
        silent=True,
    )
    add_users = AddNewUsersScript(
        class_id="1",
        user_id=1,
        session=SimpleNamespace(),
        client=_FakeAuthzClient(),
        new_ucr=new_ucr,
    )

    existing_user = SimpleNamespace(
        id=77,
        email="imported@example.com",
        first_name=None,
        last_name=None,
        display_name="Imported User",
    )

    async def _lookup_user_for_ucr(self, ucr):
        return existing_user, []

    async def _class_get_by_id(session, class_id):
        return SimpleNamespace(id=class_id, name="Class")

    async def _user_class_role_get(session, user_id, class_id):
        return SimpleNamespace(
            user_id=user_id,
            class_id=class_id,
            lms_tenant="canvas-tenant",
            lti_class_id=None,
        )

    upsert_calls = {"count": 0}

    async def _upsert_identity_external_logins(self, user_id, ucr):
        upsert_calls["count"] += 1

    monkeypatch.setattr(
        AddNewUsersScript,
        "_lookup_user_for_ucr",
        _lookup_user_for_ucr,
    )
    monkeypatch.setattr(models.Class, "get_by_id", _class_get_by_id)
    monkeypatch.setattr(models.UserClassRole, "get", _user_class_role_get)
    monkeypatch.setattr(
        AddNewUsersScript,
        "_upsert_identity_external_logins",
        _upsert_identity_external_logins,
    )

    results = await add_users.add_new_users()

    assert upsert_calls["count"] == 0
    assert len(results.results) == 1
    assert (
        results.results[0].error
        == "You cannot manually change the role of an imported user. Please update the user's role in Canvas."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "existing_lms_tenant",
        "existing_lti_class_id",
        "new_lms_tenant",
        "new_lti_class_id",
    ),
    [
        ("canvas-tenant", None, None, 42),
        (None, 42, "canvas-tenant", None),
    ],
)
async def test_add_new_users_allows_switching_between_lms_sync_sources(
    monkeypatch,
    existing_lms_tenant,
    existing_lti_class_id,
    new_lms_tenant,
    new_lti_class_id,
):
    new_ucr = schemas.CreateUserClassRoles(
        roles=[
            schemas.CreateUserClassRole(
                email="imported@example.com",
                sso_id="legacy-id",
                roles=schemas.ClassUserRoles(admin=False, teacher=True, student=False),
            )
        ],
        silent=True,
        lms_tenant=new_lms_tenant,
        lti_class_id=new_lti_class_id,
    )
    add_users = AddNewUsersScript(
        class_id="1",
        user_id=1,
        session=SimpleNamespace(),
        client=_FakeAuthzClient(),
        new_ucr=new_ucr,
    )

    existing_user = SimpleNamespace(
        id=77,
        email="imported@example.com",
        first_name=None,
        last_name=None,
        display_name="Imported User",
    )

    async def _lookup_user_for_ucr(self, ucr):
        return existing_user, []

    async def _class_get_by_id(session, class_id):
        return SimpleNamespace(id=class_id, name="Class")

    async def _user_class_role_get(session, user_id, class_id):
        return SimpleNamespace(
            user_id=user_id,
            class_id=class_id,
            lms_tenant=existing_lms_tenant,
            lti_class_id=existing_lti_class_id,
        )

    upsert_calls = {"count": 0}
    update_calls = {"count": 0}

    async def _upsert_identity_external_logins(self, user_id, ucr):
        upsert_calls["count"] += 1

    async def _update_user_enrollment(self, enrollment, roles):
        update_calls["count"] += 1

    async def _remove_deleted_users(self):
        return None

    monkeypatch.setattr(
        AddNewUsersScript,
        "_lookup_user_for_ucr",
        _lookup_user_for_ucr,
    )
    monkeypatch.setattr(models.Class, "get_by_id", _class_get_by_id)
    monkeypatch.setattr(models.UserClassRole, "get", _user_class_role_get)
    monkeypatch.setattr(
        AddNewUsersScript,
        "_upsert_identity_external_logins",
        _upsert_identity_external_logins,
    )
    monkeypatch.setattr(
        AddNewUsersScript,
        "_update_user_enrollment",
        _update_user_enrollment,
    )
    monkeypatch.setattr(
        AddNewUsersScript,
        "_remove_deleted_users",
        _remove_deleted_users,
    )

    results = await add_users.add_new_users()

    assert upsert_calls["count"] == 1
    assert update_calls["count"] == 1
    assert len(results.results) == 1
    assert results.results[0].error is None


@pytest.mark.asyncio
async def test_add_new_users_creates_external_login_when_enrollment_create_receives_none_sso(
    monkeypatch,
):
    new_ucr = schemas.CreateUserClassRoles(
        roles=[
            schemas.CreateUserClassRole(
                email="legacy@example.com",
                sso_id="legacy-id",
                roles=schemas.ClassUserRoles(admin=False, teacher=True, student=False),
            )
        ],
        sso_tenant="legacy-tenant",
        silent=True,
    )
    add_users = AddNewUsersScript(
        class_id="1",
        user_id=1,
        session=SimpleNamespace(),
        client=_FakeAuthzClient(),
        new_ucr=new_ucr,
    )

    existing_user = SimpleNamespace(
        id=88,
        email="legacy@example.com",
        first_name=None,
        last_name=None,
        display_name="Legacy User",
        dna_as_join=False,
    )

    async def _lookup_user_for_ucr(self, ucr):
        return existing_user, []

    async def _class_get_by_id(session, class_id):
        return SimpleNamespace(id=class_id, name="Class")

    async def _user_class_role_get(session, user_id, class_id):
        return None

    captured_create_args: dict[str, object] = {}

    async def _user_class_role_create(
        session,
        user_id,
        class_id,
        lms_tenant=None,
        lms_type=None,
        sso_tenant=None,
        sso_id=None,
        subscribed_to_summaries=True,
        lti_class_id=None,
    ):
        captured_create_args["sso_tenant"] = sso_tenant
        captured_create_args["sso_id"] = sso_id
        return SimpleNamespace(user_id=user_id, class_id=class_id)

    external_login_upserts: list[tuple[int, str, str]] = []

    async def _external_login_create_or_update(
        session,
        user_id,
        provider,
        identifier,
        called_by=None,
        replace_existing=True,
    ):
        external_login_upserts.append((user_id, provider, identifier))
        return True

    monkeypatch.setattr(
        AddNewUsersScript,
        "_lookup_user_for_ucr",
        _lookup_user_for_ucr,
    )
    monkeypatch.setattr(models.Class, "get_by_id", _class_get_by_id)
    monkeypatch.setattr(models.UserClassRole, "get", _user_class_role_get)
    monkeypatch.setattr(models.UserClassRole, "create", _user_class_role_create)
    monkeypatch.setattr(
        models.ExternalLogin,
        "create_or_update",
        _external_login_create_or_update,
    )

    results = await add_users.add_new_users()

    assert len(results.results) == 1
    assert results.results[0].error is None
    assert captured_create_args["sso_tenant"] is None
    assert captured_create_args["sso_id"] is None
    assert external_login_upserts == [
        (88, "legacy-tenant", "legacy-id"),
    ]

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import State

from pingpong.lti import server as server_module
from pingpong.lti.schemas import (
    LTIRegisterRequest,
    LTISetupCreateRequest,
    LTISetupLinkRequest,
)
from pingpong.schemas import LMSPlatform, LTIRegistrationReviewStatus, LTIStatus


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload


class FakeSession:
    def __init__(self, get_payload=None, post_payload=None):
        self.get_payload = get_payload
        self.post_payload = post_payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, *args, **kwargs):
        return FakeResponse(self.get_payload)

    def post(self, *args, **kwargs):
        return FakeResponse(self.post_payload)


class FakeRequest:
    def __init__(self, method="POST", payload=None, state=None):
        self.method = method
        self.query_params = payload or {}
        self._form = payload or {}
        self.state = _to_state(state)

    async def form(self):
        return self._form


class FakeDB:
    def __init__(self):
        self.added = []
        self.flushed = False
        self.refreshed = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True

    async def refresh(self, obj):
        self.refreshed.append(obj)


class FakeAuthz:
    def __init__(self, list_result=None, test_result=True):
        self.list_result = list_result or []
        self.test_result = test_result
        self.writes = []
        self.test_calls = []

    async def list(self, *args, **kwargs):
        return list(self.list_result)

    async def test(self, *args, **kwargs):
        self.test_calls.append(args)
        return self.test_result

    async def write(self, grant):
        self.writes.append(grant)


class FakeAuthzByRelation:
    """FakeAuthz that returns different results based on the relation being checked."""

    def __init__(self, relation_results=None):
        """
        relation_results: dict mapping relation names to bool results
        e.g. {"supervisor": True, "can_view": False}
        """
        self.relation_results = relation_results or {}
        self.test_calls = []
        self.writes = []

    async def list(self, *args, **kwargs):
        return []

    async def test(self, user, relation, resource):
        self.test_calls.append((user, relation, resource))
        return self.relation_results.get(relation, False)

    async def write(self, grant):
        self.writes.append(grant)


async def _async_return(value):
    return value


def _to_state(value) -> State:
    if value is None:
        return State({})
    if isinstance(value, State):
        return value
    if isinstance(value, dict):
        return State(value)
    return State(vars(value))


def _make_request_state(db=None, session_user=None, authz=None):
    return State(
        {
            "db": db or FakeDB(),
            "session": SimpleNamespace(user=session_user),
            "authz": authz or FakeAuthz(),
        }
    )


def _make_oidc_session(
    *,
    client_id="client",
    issuer="issuer",
    redirect_uri=None,
    deployment_id=None,
    consumed=False,
    expired=False,
):
    return SimpleNamespace(
        client_id=client_id,
        issuer=issuer,
        redirect_uri=redirect_uri,
        deployment_id=deployment_id,
        is_consumed=lambda: consumed,
        is_expired=lambda now: expired,
    )


def _make_lti_class(
    status=LTIStatus.PENDING,
    setup_user_id=10,
    class_id=None,
    lms_user_id=None,
    lms_course_id=None,
    lms_tenant=None,
    lms_type=None,
):
    inst = SimpleNamespace(id=1, name="Inst", default_api_key_id=7)
    registration = SimpleNamespace(institutions=[inst], id=2)
    return SimpleNamespace(
        id=123,
        registration=registration,
        registration_id=registration.id,
        lti_status=status,
        setup_user_id=setup_user_id,
        course_name="Course",
        course_code="CODE",
        course_term="Fall",
        class_id=class_id,
        lms_user_id=lms_user_id,
        lms_course_id=lms_course_id,
        lms_tenant=lms_tenant,
        lms_type=lms_type,
    )


class FakeLTIClass:
    def __init__(
        self,
        *,
        registration_id=1,
        lti_status=LTIStatus.PENDING,
        lti_platform=LMSPlatform.CANVAS,
        course_id="course-1",
        course_code=None,
        course_name=None,
        course_term=None,
        class_id=None,
        setup_user_id=10,
        context_memberships_url=None,
    ):
        self.id = 555
        self.registration_id = registration_id
        self.lti_status = lti_status
        self.lti_platform = lti_platform
        self.course_id = course_id
        self.course_code = course_code
        self.course_name = course_name
        self.course_term = course_term
        self.class_id = class_id
        self.setup_user_id = setup_user_id
        self.context_memberships_url = context_memberships_url


class FakeUserModel:
    def __init__(self, email):
        self.id = 42
        self.email = email
        self.first_name = ""
        self.last_name = ""
        self.state = None

    @staticmethod
    async def get_by_email(db, email):
        return None

    @staticmethod
    async def get_by_email_sso(db, email, provider, identifier):
        return None

    @staticmethod
    async def get_by_email_external_logins_priority(db, email, lookup_items):
        user = await FakeUserModel.get_by_email(db, email)
        if user:
            return user, [user.id]
        return None, []


@pytest.fixture(autouse=True)
def _patch_lti_external_login_io(monkeypatch):
    async def _get_or_create_by_name(db, name, **kwargs):
        return SimpleNamespace(id=999, name=name, internal_only=False)

    async def _create_or_update(*args, **kwargs):
        return True

    monkeypatch.setattr(
        server_module.ExternalLoginProvider,
        "get_or_create_by_name",
        _get_or_create_by_name,
    )
    monkeypatch.setattr(
        server_module.ExternalLogin,
        "create_or_update",
        _create_or_update,
    )


def _make_registration(
    issuer="issuer",
    client_id="client",
    auth_login_url="https://platform.example.com/auth",
    key_set_url="https://platform.example.com/jwks",
    token_algorithm="RS256",
    review_status=LTIRegistrationReviewStatus.PENDING,
    enabled=True,
    canvas_account_lti_guid=None,
):
    return SimpleNamespace(
        issuer=issuer,
        client_id=client_id,
        auth_login_url=auth_login_url,
        auth_token_url="https://platform.example.com/token",
        key_set_url=key_set_url,
        token_algorithm=token_algorithm,
        review_status=review_status,
        enabled=enabled,
        canvas_account_lti_guid=canvas_account_lti_guid,
        lms_platform=LMSPlatform.CANVAS,
        id=1,
    )


@pytest.mark.asyncio
async def test_fetch_jwks_returns_dict(monkeypatch):
    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        lambda timeout=None: FakeSession(get_payload={"keys": []}),
    )

    jwks = await server_module._fetch_jwks("https://example.com/jwks")

    assert jwks == {"keys": []}


@pytest.mark.asyncio
async def test_fetch_jwks_rejects_non_dict(monkeypatch):
    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        lambda timeout=None: FakeSession(get_payload=["bad"]),
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module._fetch_jwks("https://example.com/jwks")

    assert excinfo.value.status_code == 500


def test_select_jwk_with_kid():
    jwk = {"kid": "abc", "kty": "RSA"}
    assert server_module._select_jwk({"keys": [jwk]}, "abc") == jwk


def test_select_jwk_missing_keys():
    with pytest.raises(HTTPException) as excinfo:
        server_module._select_jwk({"keys": []}, None)
    assert excinfo.value.status_code == 500


def test_select_jwk_missing_kid_with_multiple_keys():
    with pytest.raises(HTTPException) as excinfo:
        server_module._select_jwk({"keys": [{"kid": "a"}, {"kid": "b"}]}, None)
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_verify_lti_id_token_happy_path(monkeypatch):
    header = {"alg": "RS256", "kid": "kid"}
    claims = {"sub": "user", "nonce": "nonce", "iss": "issuer", "aud": "client"}

    monkeypatch.setattr(
        server_module.jwt, "get_unverified_header", lambda token: header
    )
    monkeypatch.setattr(
        server_module,
        "_fetch_jwks",
        lambda url: _async_return({"keys": [{"kid": "kid"}]}),
    )
    monkeypatch.setattr(
        server_module.jwt.algorithms.RSAAlgorithm,
        "from_jwk",
        lambda jwk: "public-key",
    )
    monkeypatch.setattr(server_module.jwt, "decode", lambda *args, **kwargs: claims)

    result = await server_module._verify_lti_id_token(
        id_token="token",
        jwks_url="https://example.com/jwks",
        expected_issuer="issuer",
        expected_audience="client",
        expected_algorithm="RS256",
    )

    assert result["sub"] == "user"


@pytest.mark.asyncio
async def test_verify_lti_id_token_invalid_header(monkeypatch):
    monkeypatch.setattr(
        server_module.jwt,
        "get_unverified_header",
        lambda token: (_ for _ in ()).throw(server_module.jwt.PyJWTError()),
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module._verify_lti_id_token(
            id_token="token",
            jwks_url="https://example.com/jwks",
            expected_issuer="issuer",
            expected_audience="client",
            expected_algorithm="RS256",
        )

    assert excinfo.value.status_code == 400


def test_get_lti_key_manager_missing_config(monkeypatch):
    monkeypatch.setattr(server_module, "config", SimpleNamespace(lti=None))
    with pytest.raises(HTTPException) as excinfo:
        server_module.get_lti_key_manager()
    assert excinfo.value.status_code == 404


def test_get_lti_key_manager_success(monkeypatch):
    key_manager = object()
    lti = SimpleNamespace(key_store=SimpleNamespace(key_manager=key_manager))
    monkeypatch.setattr(server_module, "config", SimpleNamespace(lti=lti))
    assert server_module.get_lti_key_manager() is key_manager


@pytest.mark.asyncio
async def test_get_jwks_success():
    async def _get_public_keys_jwks():
        return {"keys": []}

    key_manager = SimpleNamespace(get_public_keys_jwks=_get_public_keys_jwks)
    assert await server_module.get_jwks(key_manager) == {"keys": []}


@pytest.mark.asyncio
async def test_get_jwks_error():
    async def _boom():
        raise RuntimeError("boom")

    key_manager = SimpleNamespace(get_public_keys_jwks=_boom)
    with pytest.raises(HTTPException) as excinfo:
        await server_module.get_jwks(key_manager)
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_get_sso_ids_filters_email(monkeypatch):
    providers = [SimpleNamespace(name="email"), SimpleNamespace(name="saml")]
    monkeypatch.setattr(
        server_module.ExternalLoginProvider,
        "get_all",
        lambda db: _async_return(providers),
    )
    request = FakeRequest(state=SimpleNamespace(db="db"))
    result = await server_module.get_sso_ids(request)
    assert [p.name for p in result["providers"]] == ["saml"]


@pytest.mark.asyncio
async def test_get_public_sso_providers(monkeypatch):
    providers = [
        SimpleNamespace(id=1, name="email", display_name="Email"),
        SimpleNamespace(id=2, name="saml", display_name="SAML"),
    ]
    monkeypatch.setattr(
        server_module.ExternalLoginProvider,
        "get_all",
        lambda db: _async_return(providers),
    )
    request = FakeRequest(state=SimpleNamespace(db="db"))
    result = await server_module.get_public_sso_providers(request)
    assert result["providers"] == [{"id": 2, "name": "saml", "display_name": "SAML"}]


@pytest.mark.asyncio
async def test_get_public_institutions(monkeypatch):
    institutions = [
        SimpleNamespace(id=2, name="B", default_api_key_id=5),
    ]
    monkeypatch.setattr(
        server_module.Institution,
        "get_all_with_default_api_key",
        lambda db: _async_return(institutions),
    )
    request = FakeRequest(state=SimpleNamespace(db="db"))
    result = await server_module.get_public_institutions(request)
    assert result["institutions"] == [{"id": 2, "name": "B"}]


@pytest.mark.asyncio
async def test_register_lti_instance_success(monkeypatch):
    platform_config = {
        "product_family_code": "canvas",
        "messages_supported": [
            {
                "type": "LtiResourceLinkRequest",
                "placements": [server_module.CANVAS_MESSAGE_PLACEMENT],
            }
        ],
    }
    openid_payload = {
        "issuer": "issuer",
        "authorization_endpoint": "https://platform.example.com/auth",
        "registration_endpoint": "https://platform.example.com/reg",
        "jwks_uri": "https://platform.example.com/jwks",
        "token_endpoint": "https://platform.example.com/token",
        "scopes_supported": server_module.REQUIRED_SCOPES,
        "id_token_signing_alg_values_supported": ["RS256"],
        "subject_types_supported": ["public"],
        server_module.PLATFORM_CONFIGURATION_KEY: platform_config,
    }
    registration_payload = {"client_id": "client"}

    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        lambda: FakeSession(
            get_payload=openid_payload, post_payload=registration_payload
        ),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "all_have_default_api_key",
        lambda db, ids: _async_return(True),
    )
    created = {}

    async def _create(db, data, institution_ids):
        created["data"] = data
        created["institution_ids"] = institution_ids

    monkeypatch.setattr(server_module.LTIRegistration, "create", _create)
    monkeypatch.setattr(
        server_module,
        "send_lti_registration_submitted",
        lambda *args, **kwargs: _async_return(None),
    )
    monkeypatch.setattr(
        server_module,
        "config",
        SimpleNamespace(
            url=lambda path: f"https://tool.example.com{path}",
            public_url="https://tool.example.com",
            email=SimpleNamespace(sender="sender"),
        ),
    )

    data = LTIRegisterRequest(
        name="PingPong",
        admin_name="Admin",
        admin_email="admin@example.com",
        provider_id=0,
        sso_field=None,
        openid_configuration="https://platform.example.com/.well-known/openid",
        registration_token="token",
        institution_ids=[1],
    )
    request = FakeRequest(state=SimpleNamespace(db="db"))

    result = await server_module.register_lti_instance(request, data)

    assert result == {"status": "ok"}
    assert created["data"]["client_id"] == "client"
    assert created["institution_ids"] == [1]


@pytest.mark.asyncio
async def test_lti_login_redirect(monkeypatch):
    registration = _make_registration()
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "create_pending",
        lambda *args, **kwargs: _async_return((1, "state", "nonce")),
    )
    monkeypatch.setattr(
        server_module,
        "config",
        SimpleNamespace(url=lambda path: f"https://tool.example.com{path}"),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    payload = {
        "client_id": "client",
        "iss": "issuer",
        "login_hint": "hint",
        "target_link_uri": "https://tool.example.com/launch",
    }
    request = FakeRequest(method="GET", payload=payload, state=SimpleNamespace(db="db"))

    response = await server_module.lti_login(request)

    assert response.status_code == 302
    assert response.headers["location"].startswith(registration.auth_login_url)


@pytest.mark.asyncio
async def test_lti_login_redirect_post(monkeypatch):
    registration = _make_registration()
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "create_pending",
        lambda *args, **kwargs: _async_return((1, "state", "nonce")),
    )
    monkeypatch.setattr(
        server_module,
        "config",
        SimpleNamespace(url=lambda path: f"https://tool.example.com{path}"),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    payload = {
        "client_id": "client",
        "iss": "issuer",
        "login_hint": "hint",
        "target_link_uri": "https://tool.example.com/launch",
    }
    request = FakeRequest(
        method="POST", payload=payload, state=SimpleNamespace(db="db")
    )

    response = await server_module.lti_login(request)

    assert response.status_code == 302
    assert response.headers["location"].startswith(registration.auth_login_url)


def test_is_instructor_and_student():
    assert server_module._is_instructor(
        ["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"]
    )
    assert server_module._is_instructor(
        ["http://purl.imsglobal.org/vocab/lis/v2/membership#ContentDeveloper"]
    )
    assert server_module._is_student(
        ["http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"]
    )
    assert server_module._is_student(
        ["http://purl.imsglobal.org/vocab/lis/v2/membership#Mentor"]
    )


@pytest.mark.asyncio
async def test_lti_launch_inactive_redirect(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.PENDING, enabled=False
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return({"nonce": "nonce"}),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=_make_request_state(),
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/lti/inactive")


@pytest.mark.asyncio
async def test_get_lti_class_for_setup(monkeypatch):
    lti_class = _make_lti_class()
    monkeypatch.setattr(
        server_module.LTIClass,
        "get_by_id_for_setup",
        lambda db, lti_class_id: _async_return(lti_class),
    )
    request = FakeRequest(
        state=SimpleNamespace(
            db="db", session=SimpleNamespace(user=SimpleNamespace(id=10))
        )
    )

    result = await server_module._get_lti_class_for_setup(request, 1)

    assert result.id == lti_class.id


@pytest.mark.asyncio
async def test_get_lti_class_for_setup_not_found(monkeypatch):
    monkeypatch.setattr(
        server_module.LTIClass,
        "get_by_id_for_setup",
        lambda db, lti_class_id: _async_return(None),
    )
    request = FakeRequest(
        state=SimpleNamespace(
            db="db", session=SimpleNamespace(user=SimpleNamespace(id=10))
        )
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module._get_lti_class_for_setup(request, 1)

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_get_lti_setup_context(monkeypatch):
    lti_class = _make_lti_class()
    lti_class.registration.institutions.append(
        SimpleNamespace(id=2, name="Other", default_api_key_id=9)
    )
    monkeypatch.setattr(
        server_module,
        "_get_lti_class_for_setup",
        lambda request, lti_class_id: _async_return(lti_class),
    )
    authz = FakeAuthz(list_result=[1])
    request = FakeRequest(
        state=SimpleNamespace(
            authz=authz, session=SimpleNamespace(user=SimpleNamespace(id=10))
        )
    )

    context = await server_module.get_lti_setup_context(request, 1)

    assert context.lti_class_id == lti_class.id
    assert context.institutions[0].id == 1


@pytest.mark.asyncio
async def test_get_lti_linkable_groups_empty(monkeypatch):
    authz = FakeAuthz(list_result=[])
    request = FakeRequest(
        state=SimpleNamespace(
            authz=authz, session=SimpleNamespace(user=SimpleNamespace(id=1))
        )
    )

    response = await server_module.get_lti_linkable_groups(request, 1)

    assert response.groups == []


@pytest.mark.asyncio
async def test_get_lti_linkable_groups(monkeypatch):
    authz = FakeAuthz(list_result=["1", "2"])
    classes = [
        SimpleNamespace(
            id="1", name="A", term="T", institution=SimpleNamespace(name="Inst")
        ),
        SimpleNamespace(id="2", name="B", term=None, institution=None),
    ]
    monkeypatch.setattr(
        server_module.Class,
        "get_all_by_id_simple",
        lambda db, ids: _async_return(classes),
    )

    request = FakeRequest(
        state=SimpleNamespace(
            db="db", authz=authz, session=SimpleNamespace(user=SimpleNamespace(id=1))
        )
    )

    response = await server_module.get_lti_linkable_groups(request, 1)

    assert len(response.groups) == 2
    assert response.groups[0].institution_name == "Inst"


@pytest.mark.asyncio
async def test_create_lti_group_success(monkeypatch):
    lti_class = _make_lti_class()

    class FakeClass:
        def __init__(self, name, term, institution_id, api_key_id):
            self.id = 99
            self.name = name
            self.term = term
            self.institution_id = institution_id
            self.api_key_id = api_key_id
            self.private = False
            self.any_can_create_assistant = False
            self.any_can_publish_assistant = False
            self.any_can_share_assistant = False
            self.any_can_publish_thread = False
            self.any_can_upload_class_file = False

    class FakeUserClassRole:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        server_module,
        "_get_lti_class_for_setup",
        lambda request, lti_class_id: _async_return(lti_class),
    )
    monkeypatch.setattr(server_module, "Class", FakeClass)
    monkeypatch.setattr(server_module, "UserClassRole", FakeUserClassRole)
    monkeypatch.setattr(
        server_module.User,
        "get_by_id",
        lambda db, user_id: _async_return(SimpleNamespace(dna_as_create=False)),
    )

    db = FakeDB()
    authz = FakeAuthz()
    request = FakeRequest(
        state=SimpleNamespace(
            db=db, authz=authz, session=SimpleNamespace(user=SimpleNamespace(id=10))
        )
    )
    body = LTISetupCreateRequest(institution_id=1, name="Group", term="Fall")

    response = await server_module.create_lti_group(request, 1, body)

    assert response.class_id == 99
    assert authz.writes


@pytest.mark.asyncio
async def test_create_lti_group_invalid_institution(monkeypatch):
    lti_class = _make_lti_class()
    lti_class.registration.institutions = [
        SimpleNamespace(id=2, name="Bad", default_api_key_id=None)
    ]
    monkeypatch.setattr(
        server_module,
        "_get_lti_class_for_setup",
        lambda request, lti_class_id: _async_return(lti_class),
    )

    request = FakeRequest(
        state=SimpleNamespace(
            db=FakeDB(),
            authz=FakeAuthz(),
            session=SimpleNamespace(user=SimpleNamespace(id=10)),
        )
    )
    body = LTISetupCreateRequest(institution_id=1, name="Group", term="Fall")

    with pytest.raises(HTTPException) as excinfo:
        await server_module.create_lti_group(request, 1, body)

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_link_lti_group_success(monkeypatch):
    lti_class = _make_lti_class()
    monkeypatch.setattr(
        server_module,
        "_get_lti_class_for_setup",
        lambda request, lti_class_id: _async_return(lti_class),
    )
    monkeypatch.setattr(
        server_module.LTIClass,
        "has_link_for_registration_and_class",
        lambda db, reg_id, class_id: _async_return(False),
    )
    request = FakeRequest(
        state=SimpleNamespace(
            db=FakeDB(),
            authz=FakeAuthz(test_result=True),
            session=SimpleNamespace(user=SimpleNamespace(id=10)),
        )
    )

    response = await server_module.link_lti_group(
        request, 1, LTISetupLinkRequest(class_id=55)
    )

    assert response.class_id == 55
    assert lti_class.lti_status == LTIStatus.LINKED


@pytest.mark.asyncio
async def test_link_lti_group_unauthorized(monkeypatch):
    lti_class = _make_lti_class()
    monkeypatch.setattr(
        server_module,
        "_get_lti_class_for_setup",
        lambda request, lti_class_id: _async_return(lti_class),
    )

    request = FakeRequest(
        state=SimpleNamespace(
            db=FakeDB(),
            authz=FakeAuthz(test_result=False),
            session=SimpleNamespace(user=SimpleNamespace(id=10)),
        )
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module.link_lti_group(request, 1, LTISetupLinkRequest(class_id=55))

    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_lti_launch_missing_state():
    request = FakeRequest(payload={"id_token": "token"}, state=_make_request_state())
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_missing_id_token():
    request = FakeRequest(payload={"state": "state"}, state=_make_request_state())
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_unknown_state(monkeypatch):
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(None),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_state_consumed(monkeypatch):
    oidc_session = _make_oidc_session(consumed=True)
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_state_expired(monkeypatch):
    oidc_session = _make_oidc_session(expired=True)
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_redirect_uri_mismatch(monkeypatch):
    oidc_session = _make_oidc_session(redirect_uri="https://bad.example.com/launch")
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_unknown_client_id(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(None),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_lti_launch_issuer_mismatch(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(issuer="other")
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_missing_nonce(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration()
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return({}),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_missing_deployment_id(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch"),
        deployment_id="deploy",
    )
    registration = _make_registration()
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return({"nonce": "nonce"}),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_deployment_id_invalid_type(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration()
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(
            {"nonce": "nonce", server_module.LTI_DEPLOYMENT_ID_CLAIM: 123}
        ),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_deployment_id_valid(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch"),
        deployment_id="deploy",
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.PENDING, enabled=False
    )
    claims = {
        "nonce": "nonce",
        server_module.LTI_DEPLOYMENT_ID_CLAIM: "deploy",
    }
    called = {}

    async def _validate_and_consume(*args, **kwargs):
        called["deployment_id"] = kwargs.get("deployment_id")
        return True

    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession, "validate_and_consume", _validate_and_consume
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert called["deployment_id"] == "deploy"
    assert response.status_code == 302
    assert response.headers["location"].endswith("/lti/inactive")


@pytest.mark.asyncio
async def test_lti_launch_validate_and_consume_failed(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration()
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return({"nonce": "nonce"}),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(None),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_missing_course_id(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return({"nonce": "nonce"}),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_no_recognized_roles(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1"
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(None),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/lti/no-role")


@pytest.mark.asyncio
async def test_lti_launch_missing_email(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    claims = {
        "nonce": "nonce",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1"
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(None),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_unknown_sso_provider(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "2",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(None),
    )
    monkeypatch.setattr(
        server_module.ExternalLoginProvider,
        "get_by_id",
        lambda db, provider_id: _async_return(None),
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_lti_launch_instructor_pending_class_redirect(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "given_name": "Ada",
        "family_name": "Lovelace",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
        ],
        "https://purl.imsglobal.org/spec/lti/claim/context": {
            "label": "CS1",
            "title": "Intro",
        },
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(None),
    )

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email",
        lambda db, email: _async_return(FakeUserModel(email)),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert "/lti/setup" in response.headers["location"]


@pytest.mark.asyncio
async def test_lti_launch_admin_and_instructor_pending_class_redirect(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator",
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor",
        ],
        "https://purl.imsglobal.org/spec/lti/claim/context": {
            "label": "CS1",
            "title": "Intro",
        },
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(None),
    )

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert "/lti/setup" in response.headers["location"]


@pytest.mark.asyncio
async def test_lti_launch_admin_only_no_user_redirect(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(None),
    )

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/lti/no-role")


@pytest.mark.asyncio
async def test_lti_launch_student_no_group_redirect(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(None),
    )

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/lti/no-group?lti_session=token")


@pytest.mark.asyncio
async def test_lti_launch_existing_lti_class_setup_user(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    lti_class = FakeLTIClass(
        lti_status=LTIStatus.LINKED,
        setup_user_id=42,
        class_id=99,
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(lti_class),
    )

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/group/99?lti_session=token")


@pytest.mark.asyncio
async def test_lti_launch_existing_class_add_user(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    class_ = SimpleNamespace(
        id=77,
        lms_user_id=7,
        lms_course_id="course-1",
        lms_tenant="tenant",
        lms_type=LMSPlatform.CANVAS,
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(class_),
    )

    class FakeAddUsers:
        def __init__(self, *args, **kwargs):
            self.called = True

        async def add_new_users(self):
            return None

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(server_module, "AddNewUsersManual", FakeAddUsers)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/group/77?lti_session=token")


@pytest.mark.asyncio
async def test_lti_launch_resume_pending_lti_class(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    pending_class = FakeLTIClass(lti_status=LTIStatus.PENDING, setup_user_id=42)
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(pending_class),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert "/lti/setup" in response.headers["location"]


@pytest.mark.asyncio
async def test_lti_launch_sso_user_update(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    claims = {
        "nonce": "nonce",
        "sub": "canvas-user-123",
        "iss": "issuer",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "5",
            "sso_value": "abc123",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(None),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)

    user = FakeUserModel("user@example.com")
    sso_provider = SimpleNamespace(id=5, name="saml")
    called = {"lookups": None, "create_or_update": [], "merge": []}

    async def _get_by_email_external_logins_priority(db, email, lookup_items):
        called["lookups"] = lookup_items
        return user, [user.id, 9999]

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email_external_logins_priority",
        _get_by_email_external_logins_priority,
    )
    monkeypatch.setattr(
        server_module.ExternalLoginProvider,
        "get_by_id",
        lambda db, provider_id: _async_return(sso_provider),
    )

    async def _create_or_update(db, user_id, provider, identifier, called_by=None):
        called["create_or_update"].append(
            {
                "provider": provider,
                "identifier": identifier,
                "user_id": user_id,
                "called_by": called_by,
            }
        )
        return True

    monkeypatch.setattr(
        server_module.ExternalLogin, "create_or_update", _create_or_update
    )

    async def _merge(db, authz, new_user_id, old_user_id):
        called["merge"].append((new_user_id, old_user_id))

    monkeypatch.setattr(server_module, "merge", _merge)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert "/lti/setup" in response.headers["location"]
    assert called["lookups"] is not None
    assert len(called["lookups"]) == 3
    assert called["lookups"][0].provider_id == 5
    assert called["lookups"][1].provider_id == 999
    assert called["lookups"][2].provider == "email"
    assert called["lookups"][2].identifier == "user@example.com"
    assert called["create_or_update"][0]["provider"] == "issuer"
    assert called["create_or_update"][1]["provider"] == "saml"
    assert called["merge"] == [(user.id, 9999)]


@pytest.mark.asyncio
async def test_lti_launch_non_lti_class_redirect_when_owner(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    class_ = SimpleNamespace(
        id=321,
        lms_user_id=42,
        lms_course_id="course-1",
        lms_tenant="tenant",
        lms_type=LMSPlatform.CANVAS,
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(class_),
    )

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/group/321?lti_session=token")


@pytest.mark.asyncio
async def test_lti_launch_non_lti_class_add_user_same_course(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    class_ = SimpleNamespace(
        id=321,
        lms_user_id=7,
        lms_course_id="course-1",
        lms_tenant="tenant",
        lms_type=LMSPlatform.CANVAS,
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(class_),
    )

    class FakeAddUsers:
        def __init__(self, *args, **kwargs):
            self.called = True

        async def add_new_users(self):
            return None

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(server_module, "AddNewUsersManual", FakeAddUsers)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/group/321?lti_session=token")


@pytest.mark.asyncio
async def test_lti_launch_non_lti_class_add_user_other_course(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    class_ = SimpleNamespace(
        id=321,
        lms_user_id=7,
        lms_course_id="other",
        lms_tenant="tenant",
        lms_type=LMSPlatform.CANVAS,
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(class_),
    )

    class FakeAddUsers:
        def __init__(self, *args, **kwargs):
            self.called = True

        async def add_new_users(self):
            return None

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(server_module, "AddNewUsersManual", FakeAddUsers)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/group/321?lti_session=token")


@pytest.mark.asyncio
async def test_lti_launch_add_user_exception(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    lti_class = FakeLTIClass(
        lti_status=LTIStatus.LINKED,
        setup_user_id=7,
        class_id=77,
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(lti_class),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)

    class FakeAddUsers:
        def __init__(self, *args, **kwargs):
            pass

        async def add_new_users(self):
            raise server_module.AddUserException(code=503)

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(server_module, "AddNewUsersManual", FakeAddUsers)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_is_supervisor_by_class_id():
    """Test _is_supervisor_by_class_id helper function."""
    authz = FakeAuthz(test_result=True)
    result = await server_module._is_supervisor_by_class_id(
        authz, user_id=42, class_id=99
    )
    assert result is True

    authz_false = FakeAuthz(test_result=False)
    result_false = await server_module._is_supervisor_by_class_id(
        authz_false, user_id=42, class_id=99
    )
    assert result_false is False


@pytest.mark.asyncio
async def test_can_view_by_class_id():
    """Test _can_view_by_class_id helper function."""
    authz = FakeAuthz(test_result=True)
    result = await server_module._can_view_by_class_id(authz, user_id=42, class_id=99)
    assert result is True

    authz_false = FakeAuthz(test_result=False)
    result_false = await server_module._can_view_by_class_id(
        authz_false, user_id=42, class_id=99
    )
    assert result_false is False


@pytest.mark.asyncio
async def test_lti_launch_admin_with_can_view_on_lti_class_redirects_to_group(
    monkeypatch,
):
    """Admin user with can_view permission on existing LTI class redirects to group."""
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    lti_class = FakeLTIClass(
        lti_status=LTIStatus.LINKED,
        setup_user_id=999,  # Different user
        class_id=77,
        registration_id=1,
    )
    claims = {
        "nonce": "nonce",
        "email": "admin@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(lti_class),
    )
    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email",
        lambda db, email: _async_return(FakeUserModel(email)),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    # Admin has can_view permission
    authz = FakeAuthz(test_result=True)
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=_make_request_state(authz=authz),
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/group/77?lti_session=token")


@pytest.mark.asyncio
async def test_lti_launch_admin_without_can_view_on_lti_class_redirects_to_no_role(
    monkeypatch,
):
    """Admin user without can_view permission on existing LTI class redirects to /lti/no-role."""
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    lti_class = FakeLTIClass(
        lti_status=LTIStatus.LINKED,
        setup_user_id=999,  # Different user
        class_id=77,
        registration_id=1,
    )
    claims = {
        "nonce": "nonce",
        "email": "admin@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(lti_class),
    )
    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email",
        lambda db, email: _async_return(FakeUserModel(email)),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    # Admin does NOT have can_view permission
    authz = FakeAuthz(test_result=False)
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=_make_request_state(authz=authz),
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/lti/no-role")


@pytest.mark.asyncio
async def test_lti_launch_admin_supervisor_creates_second_lti_class(monkeypatch):
    """Admin supervisor on LTI class with different registration creates second LTI class."""
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    # LTI class has different registration_id
    lti_class = FakeLTIClass(
        lti_status=LTIStatus.LINKED,
        setup_user_id=999,
        class_id=77,
        registration_id=2,  # Different from registration.id (1)
    )
    pp_class = SimpleNamespace(id=77, lms_user_id=999)
    claims = {
        "nonce": "nonce",
        "email": "admin@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
        ],
        "https://purl.imsglobal.org/spec/lti/claim/context": {
            "label": "CS1",
            "title": "Intro",
        },
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(lti_class),
    )
    monkeypatch.setattr(
        server_module.Class,
        "get_by_id",
        lambda db, class_id: _async_return(pp_class),
    )
    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email",
        lambda db, email: _async_return(FakeUserModel(email)),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    # Admin has supervisor permission (used to determine if they can create LTI class link)
    # and can_view permission (used to determine if they can access the group)
    authz = FakeAuthzByRelation(relation_results={"supervisor": True, "can_view": True})
    db = FakeDB()
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=_make_request_state(db=db, authz=authz),
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    # Should create second LTI class and redirect to group
    assert response.status_code == 302
    assert response.headers["location"].endswith("/group/77?lti_session=token")
    # Check that a new LTI class was added
    assert any(isinstance(obj, FakeLTIClass) for obj in db.added)
    # Verify supervisor check was called (this determines LTI class creation)
    assert any(call[1] == "supervisor" for call in authz.test_calls)


@pytest.mark.asyncio
async def test_lti_launch_admin_non_supervisor_does_not_create_second_lti_class(
    monkeypatch,
):
    """Admin who is not a supervisor should NOT create a second LTI class link."""
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    # LTI class has different registration_id
    lti_class = FakeLTIClass(
        lti_status=LTIStatus.LINKED,
        setup_user_id=999,
        class_id=77,
        registration_id=2,  # Different from registration.id (1)
    )
    pp_class = SimpleNamespace(id=77, lms_user_id=999)
    claims = {
        "nonce": "nonce",
        "email": "admin@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
        ],
        "https://purl.imsglobal.org/spec/lti/claim/context": {
            "label": "CS1",
            "title": "Intro",
        },
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(lti_class),
    )
    monkeypatch.setattr(
        server_module.Class,
        "get_by_id",
        lambda db, class_id: _async_return(pp_class),
    )
    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email",
        lambda db, email: _async_return(FakeUserModel(email)),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    # Admin does NOT have supervisor permission (so no LTI class created)
    # and does NOT have can_view permission (so redirects to no-role)
    authz = FakeAuthzByRelation(
        relation_results={"supervisor": False, "can_view": False}
    )
    db = FakeDB()
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=_make_request_state(db=db, authz=authz),
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    # Should redirect to /lti/no-role since admin can't view class
    assert response.status_code == 302
    assert response.headers["location"].endswith("/lti/no-role")
    # Verify NO new LTI class was added (only User is added)
    assert not any(isinstance(obj, FakeLTIClass) for obj in db.added)
    # Verify supervisor check was called
    assert any(call[1] == "supervisor" for call in authz.test_calls)
    # Verify can_view check was called (after supervisor check failed)
    assert any(call[1] == "can_view" for call in authz.test_calls)


@pytest.mark.asyncio
async def test_lti_launch_admin_non_supervisor_does_not_create_lti_class_for_non_lti_class(
    monkeypatch,
):
    """Admin who is not a supervisor should NOT create a new LTI class for non-LTI class."""
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    # Non-LTI class (regular class)
    class_ = SimpleNamespace(
        id=321,
        lms_user_id=999,  # Different owner
        lms_course_id="course-1",
        lms_tenant="tenant",
        lms_type=LMSPlatform.CANVAS,
    )
    claims = {
        "nonce": "nonce",
        "email": "admin@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
        ],
        "https://purl.imsglobal.org/spec/lti/claim/context": {
            "label": "CS1",
            "title": "Intro",
        },
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(class_),
    )
    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email",
        lambda db, email: _async_return(FakeUserModel(email)),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    # Admin does NOT have supervisor permission (so no LTI class created)
    # and does NOT have can_view permission (so redirects to no-role)
    authz = FakeAuthzByRelation(
        relation_results={"supervisor": False, "can_view": False}
    )
    db = FakeDB()
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=_make_request_state(db=db, authz=authz),
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    # Should redirect to /lti/no-role since admin can't view class
    assert response.status_code == 302
    assert response.headers["location"].endswith("/lti/no-role")
    # Verify NO new LTI class was added (only User is added)
    assert not any(isinstance(obj, FakeLTIClass) for obj in db.added)
    # Verify supervisor check was called
    assert any(call[1] == "supervisor" for call in authz.test_calls)
    # Verify can_view check was called (after supervisor check failed)
    assert any(call[1] == "can_view" for call in authz.test_calls)


@pytest.mark.asyncio
async def test_lti_launch_admin_with_can_view_on_second_lti_class_redirects_to_group(
    monkeypatch,
):
    """Admin with can_view on LTI class with different registration (not owner) redirects to group."""
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    lti_class = FakeLTIClass(
        lti_status=LTIStatus.LINKED,
        setup_user_id=999,
        class_id=77,
        registration_id=2,  # Different registration
    )
    pp_class = SimpleNamespace(id=77, lms_user_id=999)  # Different owner
    claims = {
        "nonce": "nonce",
        "email": "admin@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(lti_class),
    )
    monkeypatch.setattr(
        server_module.Class,
        "get_by_id",
        lambda db, class_id: _async_return(pp_class),
    )
    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email",
        lambda db, email: _async_return(FakeUserModel(email)),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    # Admin has can_view permission
    authz = FakeAuthz(test_result=True)
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=_make_request_state(authz=authz),
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/group/77?lti_session=token")


@pytest.mark.asyncio
async def test_lti_launch_admin_without_can_view_on_second_lti_class_redirects_to_no_role(
    monkeypatch,
):
    """Admin without can_view on LTI class with different registration redirects to /lti/no-role."""
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    lti_class = FakeLTIClass(
        lti_status=LTIStatus.LINKED,
        setup_user_id=999,
        class_id=77,
        registration_id=2,  # Different registration
    )
    pp_class = SimpleNamespace(id=77, lms_user_id=999)
    claims = {
        "nonce": "nonce",
        "email": "admin@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(lti_class),
    )
    monkeypatch.setattr(
        server_module.Class,
        "get_by_id",
        lambda db, class_id: _async_return(pp_class),
    )
    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email",
        lambda db, email: _async_return(FakeUserModel(email)),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    # Admin does NOT have can_view permission
    authz = FakeAuthz(test_result=False)
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=_make_request_state(authz=authz),
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/lti/no-role")


@pytest.mark.asyncio
async def test_lti_launch_admin_supervisor_creates_new_lti_class_for_non_lti_class(
    monkeypatch,
):
    """Admin supervisor on non-LTI class creates new LTI class."""
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    # Non-LTI class (regular class, not FakeLTIClass)
    class_ = SimpleNamespace(
        id=321,
        lms_user_id=999,  # Different owner
        lms_course_id="course-1",
        lms_tenant="tenant",
        lms_type=LMSPlatform.CANVAS,
    )
    claims = {
        "nonce": "nonce",
        "email": "admin@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
        ],
        "https://purl.imsglobal.org/spec/lti/claim/context": {
            "label": "CS1",
            "title": "Intro",
        },
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(class_),
    )
    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email",
        lambda db, email: _async_return(FakeUserModel(email)),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    # Admin has supervisor permission (used to determine if they can create LTI class link)
    # and can_view permission (used to determine if they can access the group)
    authz = FakeAuthzByRelation(relation_results={"supervisor": True, "can_view": True})
    db = FakeDB()
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=_make_request_state(db=db, authz=authz),
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    # Should create new LTI class and redirect to group
    assert response.status_code == 302
    assert response.headers["location"].endswith("/group/321?lti_session=token")
    # Check that a new LTI class was added
    assert any(isinstance(obj, FakeLTIClass) for obj in db.added)
    # Verify supervisor check was called (this determines LTI class creation)
    assert any(call[1] == "supervisor" for call in authz.test_calls)


@pytest.mark.asyncio
async def test_lti_launch_admin_with_can_view_on_non_lti_class_redirects_to_group(
    monkeypatch,
):
    """Admin with can_view on non-LTI class (not owner) redirects to group."""
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    class_ = SimpleNamespace(
        id=321,
        lms_user_id=999,  # Different owner
        lms_course_id="other",  # Different course
        lms_tenant="tenant",
        lms_type=LMSPlatform.CANVAS,
    )
    claims = {
        "nonce": "nonce",
        "email": "admin@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(class_),
    )
    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email",
        lambda db, email: _async_return(FakeUserModel(email)),
    )
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    # Admin has can_view permission
    authz = FakeAuthz(test_result=True)
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=_make_request_state(authz=authz),
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/group/321?lti_session=token")


@pytest.mark.asyncio
async def test_lti_launch_admin_without_can_view_on_non_lti_class_redirects_to_no_role(
    monkeypatch,
):
    """Admin without can_view on non-LTI class redirects to /lti/no-role."""
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    class_ = SimpleNamespace(
        id=321,
        lms_user_id=999,  # Different owner
        lms_course_id="other",  # Different course
        lms_tenant="tenant",
        lms_type=LMSPlatform.CANVAS,
    )
    claims = {
        "nonce": "nonce",
        "email": "admin@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/custom": {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
        ],
    }
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "get_by_state",
        lambda db, state: _async_return(oidc_session),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "get_by_client_id",
        lambda db, client_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "_verify_lti_id_token",
        lambda **kwargs: _async_return(claims),
    )
    monkeypatch.setattr(
        server_module.LTIOIDCSession,
        "validate_and_consume",
        lambda *args, **kwargs: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(class_),
    )
    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email",
        lambda db, email: _async_return(FakeUserModel(email)),
    )
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    # Admin does NOT have can_view permission
    authz = FakeAuthz(test_result=False)
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=_make_request_state(authz=authz),
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert response.headers["location"].endswith("/lti/no-role")

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from multidict import CIMultiDict
import pytest
from fastapi import HTTPException
from starlette.datastructures import State
from yarl import URL

import pingpong.config as config_module
from pingpong.lti import server as server_module
from pingpong.lti.constants import CANVAS_MESSAGE_PLACEMENT
from pingpong.lti.platforms import canvas as canvas_module
from pingpong.lti.platforms.canvas import CanvasPlatformHandler
from pingpong.lti.schemas import (
    LTIRegisterRequest,
    LTISetupCreateRequest,
    LTISetupLinkRequest,
)
from pingpong.schemas import (
    LMSType,
    LMSPlatform,
    LTIRegistrationReviewStatus,
    LTIStatus,
)


class FakeResponse:
    def __init__(self, payload, *, status=200, headers=None):
        self._payload = payload
        self.status = status
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload


class FakeRequestContext:
    def __init__(self, session, method, url, kwargs):
        self.session = session
        self.method = method
        self.url = url
        self.kwargs = kwargs
        self.response = None

    async def __aenter__(self):
        self.response = await self.session._request(
            self.method, self.url, **self.kwargs
        )
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(
        self,
        get_payload=None,
        post_payload=None,
        *,
        get_responses=None,
        post_responses=None,
        trace_configs=None,
    ):
        self.get_payload = get_payload
        self.post_payload = post_payload
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.get_calls = []
        self.post_calls = []
        self._trace_configs = list(trace_configs or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def request(self, method, url, **kwargs):
        return FakeRequestContext(self, method, url, kwargs)

    async def _request(self, method, url, **kwargs):
        current_method = method.upper()
        current_url = url
        current_headers = dict(kwargs.get("headers") or {})
        current_json = kwargs.get("json")
        current_data = kwargs.get("data")
        allow_redirects = kwargs.get("allow_redirects", True)

        while True:
            response_pool = (
                self.get_responses if current_method == "GET" else self.post_responses
            )
            payload = self.get_payload if current_method == "GET" else self.post_payload
            request_kwargs = dict(kwargs)
            request_kwargs["headers"] = current_headers.copy()
            request_kwargs["allow_redirects"] = allow_redirects
            if "json" in kwargs or current_json is not None:
                request_kwargs["json"] = current_json
            if "data" in kwargs or current_data is not None:
                request_kwargs["data"] = current_data

            call = ((current_url,), request_kwargs)
            if current_method == "GET":
                self.get_calls.append(call)
            else:
                self.post_calls.append(call)

            response = response_pool.pop(0) if response_pool else FakeResponse(payload)
            if response.status not in {301, 302, 303, 307, 308} or not allow_redirects:
                return response

            for trace_config in self._trace_configs:
                trace_ctx = trace_config.trace_config_ctx(
                    kwargs.get("trace_request_ctx")
                )
                params = SimpleNamespace(
                    method=current_method,
                    url=URL(current_url),
                    headers=CIMultiDict(current_headers),
                    response=response,
                )
                await trace_config.on_request_redirect.send(self, trace_ctx, params)

            redirect_url = URL(current_url).join(
                URL(response.headers.get("Location") or response.headers.get("URI"))
            )
            if URL(current_url).origin() != redirect_url.origin():
                current_headers.pop("Authorization", None)

            if (response.status == 303 and current_method != "HEAD") or (
                response.status in {301, 302} and current_method == "POST"
            ):
                current_method = "GET"
                current_json = None
                current_data = None

            current_url = str(redirect_url)


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


def _client_session_factory(fake_session: FakeSession):
    def _factory(*args, **kwargs):
        fake_session._trace_configs = list(kwargs.get("trace_configs") or [])
        return fake_session

    return _factory


def _fake_session_factory(**session_kwargs):
    def _factory(*args, **kwargs):
        return FakeSession(
            trace_configs=kwargs.get("trace_configs"),
            **session_kwargs,
        )

    return _factory


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
        resource_link_id=None,
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
        resource_link_id=None,
    ):
        self.id = 555
        self.registration_id = registration_id
        self.lti_status = lti_status
        self.lti_platform = lti_platform
        self.course_id = course_id
        self.resource_link_id = resource_link_id
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


@pytest.fixture(autouse=True)
def _patch_lti_security_config(monkeypatch):
    real_config = config_module.config
    allow_deny = SimpleNamespace(allow=["*"], deny=[])
    url_security = SimpleNamespace(
        allow_http_in_development=True,
        allow_redirects=True,
        hosts=allow_deny,
        paths=allow_deny,
    )
    security = SimpleNamespace(
        allow_http_in_development=True,
        allow_redirects=True,
        hosts=allow_deny,
        paths=allow_deny,
        authorization_endpoint=url_security,
        jwks_uri=url_security,
        names_and_role_endpoint=url_security,
        openid_configuration=url_security,
        registration_endpoint=url_security,
        token_endpoint=url_security,
    )
    lti = SimpleNamespace(security=security)
    patched_config = SimpleNamespace(
        lti=lti,
        development=False,
        url=real_config.url,
        public_url=real_config.public_url,
    )
    monkeypatch.setattr(config_module, "config", patched_config)
    monkeypatch.setattr(server_module, "config", patched_config)


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
        _fake_session_factory(get_payload={"keys": []}),
    )

    jwks = await server_module._fetch_jwks("https://example.com/jwks")

    assert jwks == {"keys": []}


@pytest.mark.asyncio
async def test_fetch_jwks_rejects_non_dict(monkeypatch):
    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _fake_session_factory(get_payload=["bad"]),
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module._fetch_jwks("https://example.com/jwks")

    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_fetch_jwks_returns_bad_gateway_for_invalid_json(monkeypatch):
    class InvalidJSONResponse(FakeResponse):
        async def json(self):
            raise json.JSONDecodeError("Expecting value", "<html>", 0)

    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _fake_session_factory(get_responses=[InvalidJSONResponse(None)]),
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module._fetch_jwks("https://example.com/jwks")

    assert excinfo.value.status_code == 502
    assert excinfo.value.detail == "Invalid JSON from jwks_url"


@pytest.mark.asyncio
async def test_fetch_jwks_rejects_redirect_to_unallowlisted_host(monkeypatch):
    allow_deny = SimpleNamespace(allow=["example.com"], deny=[])
    url_security = SimpleNamespace(
        allow_http_in_development=True,
        allow_redirects=True,
        hosts=allow_deny,
        paths=SimpleNamespace(allow=["/jwks"], deny=[]),
    )
    restricted_config = SimpleNamespace(
        lti=SimpleNamespace(
            security=SimpleNamespace(
                allow_http_in_development=True,
                allow_redirects=True,
                hosts=allow_deny,
                paths=SimpleNamespace(allow=["*"], deny=[]),
                authorization_endpoint=url_security,
                jwks_uri=url_security,
                names_and_role_endpoint=url_security,
                openid_configuration=url_security,
                registration_endpoint=url_security,
                token_endpoint=url_security,
            )
        ),
        development=False,
    )
    monkeypatch.setattr(config_module, "config", restricted_config)
    monkeypatch.setattr(server_module, "config", restricted_config)
    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _fake_session_factory(
            get_responses=[
                FakeResponse(
                    None,
                    status=302,
                    headers={"Location": "https://evil.example.com/jwks"},
                )
            ]
        ),
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module._fetch_jwks("https://example.com/jwks")

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid jwks_url"


@pytest.mark.asyncio
async def test_fetch_jwks_rejects_redirect_that_requires_rewriting(monkeypatch):
    allow_deny = SimpleNamespace(allow=["example.com"], deny=[])
    url_security = SimpleNamespace(
        allow_http_in_development=True,
        allow_redirects=True,
        hosts=allow_deny,
        paths=SimpleNamespace(allow=["/jwks"], deny=[]),
    )
    restricted_config = SimpleNamespace(
        lti=SimpleNamespace(
            security=SimpleNamespace(
                allow_http_in_development=True,
                allow_redirects=True,
                hosts=allow_deny,
                paths=SimpleNamespace(allow=["*"], deny=[]),
                authorization_endpoint=url_security,
                jwks_uri=url_security,
                names_and_role_endpoint=url_security,
                openid_configuration=url_security,
                registration_endpoint=url_security,
                token_endpoint=url_security,
            )
        ),
        development=False,
    )
    monkeypatch.setattr(config_module, "config", restricted_config)
    monkeypatch.setattr(server_module, "config", restricted_config)
    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _fake_session_factory(
            get_responses=[
                FakeResponse(
                    None,
                    status=302,
                    headers={"Location": "https://example.com./jwks"},
                )
            ]
        ),
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module._fetch_jwks("https://example.com/jwks")

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid jwks_url"


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


def test_get_claim_object_returns_empty_dict_for_non_dict_claims():
    claims = {
        server_module.LTI_CLAIM_NRPS_KEY: "not-a-dict",
        server_module.LTI_CLAIM_CUSTOM_KEY: ["also-not-a-dict"],
    }

    assert (
        server_module._get_claim_object(claims, server_module.LTI_CLAIM_NRPS_KEY) == {}
    )
    assert (
        server_module._get_claim_object(claims, server_module.LTI_CLAIM_CUSTOM_KEY)
        == {}
    )
    assert server_module._get_claim_object(claims, "missing-claim") == {}


def test_get_claim_object_returns_dict_for_dict_claim():
    claim_value = {"context_memberships_url": "https://example.com/nrps"}
    claims = {server_module.LTI_CLAIM_NRPS_KEY: claim_value}

    assert (
        server_module._get_claim_object(claims, server_module.LTI_CLAIM_NRPS_KEY)
        == claim_value
    )


def test_canvas_extract_course_metadata_filters_non_string_values():
    claims = {
        server_module.LTI_CLAIM_CONTEXT_KEY: {
            "label": 123,
            "title": ["Course Name"],
        },
        server_module.LTI_CLAIM_NRPS_KEY: {
            "context_memberships_url": "https://example.com/nrps"
        },
    }

    (
        course_code,
        course_name,
        course_term,
        context_memberships_url,
    ) = CanvasPlatformHandler().extract_course_metadata(
        claims,
        {"canvas_term_name": {"name": "Fall"}},
    )

    assert course_code is None
    assert course_name is None
    assert course_term is None
    assert context_memberships_url == "https://example.com/nrps"


def test_canvas_extract_course_metadata_rejects_invalid_context_memberships_url():
    claims = {
        server_module.LTI_CLAIM_NRPS_KEY: {
            "context_memberships_url": "not-a-url",
        },
    }

    with pytest.raises(HTTPException) as excinfo:
        CanvasPlatformHandler().extract_course_metadata(claims, {})

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid context_memberships_url"


@pytest.mark.parametrize("claim_value", ["", "   "])
def test_canvas_extract_course_metadata_treats_blank_context_memberships_url_as_missing(
    claim_value,
):
    claims = {
        server_module.LTI_CLAIM_NRPS_KEY: {
            "context_memberships_url": claim_value,
        },
    }

    _, _, _, context_memberships_url = CanvasPlatformHandler().extract_course_metadata(
        claims, {}
    )

    assert context_memberships_url is None


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
async def test_get_lti_register_setup_canvas(monkeypatch):
    providers = [
        SimpleNamespace(id=1, name="email", display_name="Email"),
        SimpleNamespace(id=2, name="saml", display_name="SAML"),
        SimpleNamespace(id=3, name="okta", display_name="Okta", internal_only=True),
    ]
    institutions = [
        SimpleNamespace(id=2, name="B", default_api_key_id=5),
    ]
    monkeypatch.setattr(
        server_module,
        "_resolve_platform",
        lambda openid_configuration, registration_token: _async_return(
            (LMSPlatform.CANVAS, {})
        ),
    )
    monkeypatch.setattr(
        server_module.ExternalLoginProvider,
        "get_all",
        lambda db: _async_return(providers),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "get_all_with_default_api_key",
        lambda db: _async_return(institutions),
    )
    request = FakeRequest(state=SimpleNamespace(db="db"))
    result = await server_module.get_lti_register_setup(
        request,
        SimpleNamespace(
            openid_configuration="https://platform.example.com/openid",
            registration_token="token",
        ),
    )
    assert result["providers"] == [{"id": 2, "name": "saml", "display_name": "SAML"}]
    assert result["institutions"] == [{"id": 2, "name": "B"}]
    assert result["show_course_navigation_control"] is True


@pytest.mark.asyncio
async def test_get_lti_register_setup_harvard_lxp(monkeypatch):
    providers = [
        SimpleNamespace(id=1, name="email", display_name="Email"),
        SimpleNamespace(id=2, name="saml", display_name="SAML"),
    ]
    institutions = [
        SimpleNamespace(id=2, name="B", default_api_key_id=5),
    ]
    monkeypatch.setattr(
        server_module,
        "_resolve_platform",
        lambda openid_configuration, registration_token: _async_return(
            (LMSPlatform.HARVARD_LXP, {})
        ),
    )
    monkeypatch.setattr(
        server_module.ExternalLoginProvider,
        "get_all",
        lambda db: _async_return(providers),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "get_all_with_default_api_key",
        lambda db: _async_return(institutions),
    )
    request = FakeRequest(state=SimpleNamespace(db="db"))
    result = await server_module.get_lti_register_setup(
        request,
        SimpleNamespace(
            openid_configuration="https://platform.example.com/openid",
            registration_token="token",
        ),
    )
    assert result["providers"] == []
    assert result["institutions"] == [{"id": 2, "name": "B"}]
    assert result["show_course_navigation_control"] is False


@pytest.mark.asyncio
async def test_register_lti_instance_success(monkeypatch):
    platform_config = {
        "product_family_code": "canvas",
        "messages_supported": [
            {
                "type": "LtiResourceLinkRequest",
                "placements": [CANVAS_MESSAGE_PLACEMENT],
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
        _fake_session_factory(
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
            lti=config_module.config.lti,
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
async def test_register_lti_instance_rejects_non_string_registration_endpoint(
    monkeypatch,
):
    platform_config = {
        "product_family_code": "canvas",
        "messages_supported": [
            {
                "type": "LtiResourceLinkRequest",
                "placements": [CANVAS_MESSAGE_PLACEMENT],
            }
        ],
    }
    openid_payload = {
        "issuer": "issuer",
        "authorization_endpoint": "https://platform.example.com/auth",
        "registration_endpoint": {"url": "https://platform.example.com/reg"},
        "jwks_uri": "https://platform.example.com/jwks",
        "token_endpoint": "https://platform.example.com/token",
        "scopes_supported": server_module.REQUIRED_SCOPES,
        "id_token_signing_alg_values_supported": ["RS256"],
        "subject_types_supported": ["public"],
        server_module.PLATFORM_CONFIGURATION_KEY: platform_config,
    }

    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _fake_session_factory(get_payload=openid_payload),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "all_have_default_api_key",
        lambda db, ids: _async_return(True),
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

    with pytest.raises(HTTPException) as excinfo:
        await server_module.register_lti_instance(request, data)

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Missing required OpenID configuration fields"


@pytest.mark.asyncio
async def test_register_lti_instance_rejects_openid_redirect_to_unallowlisted_host(
    monkeypatch,
):
    allow_deny = SimpleNamespace(allow=["platform.example.com"], deny=[])
    url_security = SimpleNamespace(
        allow_http_in_development=True,
        allow_redirects=True,
        hosts=allow_deny,
        paths=SimpleNamespace(allow=["/.well-known/*"], deny=[]),
    )
    restricted_config = SimpleNamespace(
        lti=SimpleNamespace(
            security=SimpleNamespace(
                allow_http_in_development=True,
                allow_redirects=True,
                hosts=allow_deny,
                paths=SimpleNamespace(allow=["*"], deny=[]),
                authorization_endpoint=url_security,
                jwks_uri=url_security,
                names_and_role_endpoint=url_security,
                openid_configuration=url_security,
                registration_endpoint=url_security,
                token_endpoint=url_security,
            )
        ),
        development=False,
    )
    monkeypatch.setattr(config_module, "config", restricted_config)
    monkeypatch.setattr(
        server_module,
        "config",
        SimpleNamespace(
            url=lambda path: f"https://tool.example.com{path}",
            public_url="https://tool.example.com",
            email=SimpleNamespace(sender="sender"),
            lti=restricted_config.lti,
        ),
    )
    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _fake_session_factory(
            get_responses=[
                FakeResponse(
                    None,
                    status=302,
                    headers={"Location": "https://evil.example.com/.well-known/openid"},
                )
            ]
        ),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "all_have_default_api_key",
        lambda db, ids: _async_return(True),
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

    with pytest.raises(HTTPException) as excinfo:
        await server_module.register_lti_instance(request, data)

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid openid_configuration"


@pytest.mark.asyncio
async def test_register_lti_instance_returns_bad_gateway_for_invalid_openid_json(
    monkeypatch,
):
    class InvalidJSONResponse(FakeResponse):
        async def json(self):
            raise json.JSONDecodeError("Expecting value", "<html>", 0)

    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _fake_session_factory(get_responses=[InvalidJSONResponse(None)]),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "all_have_default_api_key",
        lambda db, ids: _async_return(True),
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

    with pytest.raises(HTTPException) as excinfo:
        await server_module.register_lti_instance(request, data)

    assert excinfo.value.status_code == 502
    assert excinfo.value.detail == "Invalid OpenID configuration response payload"


@pytest.mark.asyncio
async def test_register_lti_instance_rejects_invalid_authorization_endpoint(
    monkeypatch,
):
    platform_config = {
        "product_family_code": "canvas",
        "messages_supported": [
            {
                "type": "LtiResourceLinkRequest",
                "placements": [CANVAS_MESSAGE_PLACEMENT],
            }
        ],
    }
    openid_payload = {
        "issuer": "issuer",
        "authorization_endpoint": "not-a-url",
        "registration_endpoint": "https://platform.example.com/reg",
        "jwks_uri": "https://platform.example.com/jwks",
        "token_endpoint": "https://platform.example.com/token",
        "scopes_supported": server_module.REQUIRED_SCOPES,
        "id_token_signing_alg_values_supported": ["RS256"],
        "subject_types_supported": ["public"],
        server_module.PLATFORM_CONFIGURATION_KEY: platform_config,
    }

    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _fake_session_factory(get_payload=openid_payload),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "all_have_default_api_key",
        lambda db, ids: _async_return(True),
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

    with pytest.raises(HTTPException) as excinfo:
        await server_module.register_lti_instance(request, data)

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid URL for authorization endpoint"


@pytest.mark.asyncio
async def test_register_lti_instance_does_not_forward_auth_to_openid_redirect(
    monkeypatch,
):
    platform_config = {
        "product_family_code": "canvas",
        "messages_supported": [
            {
                "type": "LtiResourceLinkRequest",
                "placements": [CANVAS_MESSAGE_PLACEMENT],
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
    session = FakeSession(
        get_responses=[
            FakeResponse(
                None,
                status=302,
                headers={
                    "Location": "https://redirected.example.com/.well-known/openid"
                },
            ),
            FakeResponse(openid_payload),
        ],
        post_payload={"client_id": "client"},
    )

    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _client_session_factory(session),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "all_have_default_api_key",
        lambda db, ids: _async_return(True),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "create",
        lambda db, data, institution_ids: _async_return(None),
    )
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
            lti=config_module.config.lti,
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
    assert len(session.get_calls) == 2
    first_args, first_kwargs = session.get_calls[0]
    second_args, second_kwargs = session.get_calls[1]
    assert first_args[0] == "https://platform.example.com/.well-known/openid"
    assert second_args[0] == "https://redirected.example.com/.well-known/openid"
    assert first_kwargs["headers"]["Authorization"] == "Bearer token"
    assert second_kwargs["headers"] == {}


@pytest.mark.asyncio
async def test_register_lti_instance_preserves_auth_on_same_origin_openid_redirect(
    monkeypatch,
):
    platform_config = {
        "product_family_code": "canvas",
        "messages_supported": [
            {
                "type": "LtiResourceLinkRequest",
                "placements": [CANVAS_MESSAGE_PLACEMENT],
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
    session = FakeSession(
        get_responses=[
            FakeResponse(
                None,
                status=302,
                headers={"Location": "/.well-known/openid-redirect"},
            ),
            FakeResponse(openid_payload),
        ],
        post_payload={"client_id": "client"},
    )

    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _client_session_factory(session),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "all_have_default_api_key",
        lambda db, ids: _async_return(True),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "create",
        lambda db, data, institution_ids: _async_return(None),
    )
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
            lti=config_module.config.lti,
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
    assert len(session.get_calls) == 2
    first_args, first_kwargs = session.get_calls[0]
    second_args, second_kwargs = session.get_calls[1]
    assert first_args[0] == "https://platform.example.com/.well-known/openid"
    assert second_args[0] == "https://platform.example.com/.well-known/openid-redirect"
    assert first_kwargs["headers"]["Authorization"] == "Bearer token"
    assert second_kwargs["headers"]["Authorization"] == "Bearer token"


@pytest.mark.asyncio
async def test_register_lti_instance_returns_bad_gateway_for_invalid_registration_json(
    monkeypatch,
):
    class InvalidJSONResponse(FakeResponse):
        async def json(self):
            raise json.JSONDecodeError("Expecting value", "<html>", 0)

    platform_config = {
        "product_family_code": "canvas",
        "messages_supported": [
            {
                "type": "LtiResourceLinkRequest",
                "placements": [CANVAS_MESSAGE_PLACEMENT],
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

    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _fake_session_factory(
            get_payload=openid_payload,
            post_responses=[InvalidJSONResponse(None)],
        ),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "all_have_default_api_key",
        lambda db, ids: _async_return(True),
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

    with pytest.raises(HTTPException) as excinfo:
        await server_module.register_lti_instance(request, data)

    assert excinfo.value.status_code == 502
    assert excinfo.value.detail == "Invalid JSON from registration_endpoint"


@pytest.mark.asyncio
async def test_register_lti_instance_converts_post_302_redirect_to_get(
    monkeypatch,
):
    platform_config = {
        "product_family_code": "canvas",
        "messages_supported": [
            {
                "type": "LtiResourceLinkRequest",
                "placements": [CANVAS_MESSAGE_PLACEMENT],
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
    session = FakeSession(
        post_responses=[
            FakeResponse(
                None,
                status=302,
                headers={"Location": "/reg-redirect"},
            ),
        ],
        get_responses=[
            FakeResponse(openid_payload),
            FakeResponse({"client_id": "client"}),
        ],
    )

    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _client_session_factory(session),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "all_have_default_api_key",
        lambda db, ids: _async_return(True),
    )
    monkeypatch.setattr(
        server_module.LTIRegistration,
        "create",
        lambda db, data, institution_ids: _async_return(None),
    )
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
            lti=config_module.config.lti,
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
    assert len(session.post_calls) == 1
    assert len(session.get_calls) == 2
    first_args, first_kwargs = session.post_calls[0]
    second_args, second_kwargs = session.get_calls[1]
    assert first_args[0] == "https://platform.example.com/reg"
    assert second_args[0] == "https://platform.example.com/reg-redirect"
    assert first_kwargs["allow_redirects"] is True
    assert second_kwargs["allow_redirects"] is True
    assert first_kwargs["json"]["client_name"] == "PingPong"
    assert second_kwargs["json"] is None
    assert second_kwargs["headers"]["Authorization"] == "Bearer token"


@pytest.mark.asyncio
async def test_register_lti_instance_rejects_registration_redirect_to_unallowlisted_host(
    monkeypatch,
):
    allow_deny = SimpleNamespace(allow=["platform.example.com"], deny=[])
    redirect_limited_url_security = SimpleNamespace(
        allow_http_in_development=True,
        allow_redirects=True,
        hosts=allow_deny,
        paths=SimpleNamespace(allow=["/.well-known/*"], deny=[]),
    )
    permissive_url_security = SimpleNamespace(
        allow_http_in_development=True,
        allow_redirects=True,
        hosts=allow_deny,
        paths=SimpleNamespace(allow=["*"], deny=[]),
    )
    restricted_config = SimpleNamespace(
        lti=SimpleNamespace(
            security=SimpleNamespace(
                allow_http_in_development=True,
                allow_redirects=True,
                hosts=allow_deny,
                paths=SimpleNamespace(allow=["*"], deny=[]),
                authorization_endpoint=permissive_url_security,
                jwks_uri=permissive_url_security,
                names_and_role_endpoint=permissive_url_security,
                openid_configuration=redirect_limited_url_security,
                registration_endpoint=permissive_url_security,
                token_endpoint=permissive_url_security,
            )
        ),
        development=False,
    )
    monkeypatch.setattr(config_module, "config", restricted_config)
    monkeypatch.setattr(
        server_module,
        "config",
        SimpleNamespace(
            url=lambda path: f"https://tool.example.com{path}",
            public_url="https://tool.example.com",
            email=SimpleNamespace(sender="sender"),
            lti=restricted_config.lti,
        ),
    )
    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _fake_session_factory(
            get_payload={
                "issuer": "issuer",
                "authorization_endpoint": "https://platform.example.com/auth",
                "registration_endpoint": "https://platform.example.com/reg",
                "jwks_uri": "https://platform.example.com/jwks",
                "token_endpoint": "https://platform.example.com/token",
                "scopes_supported": server_module.REQUIRED_SCOPES,
                "id_token_signing_alg_values_supported": ["RS256"],
                "subject_types_supported": ["public"],
                server_module.PLATFORM_CONFIGURATION_KEY: {
                    "product_family_code": "canvas",
                    "messages_supported": [
                        {
                            "type": "LtiResourceLinkRequest",
                            "placements": [CANVAS_MESSAGE_PLACEMENT],
                        }
                    ],
                },
            },
            post_responses=[
                FakeResponse(
                    None,
                    status=302,
                    headers={"Location": "https://evil.example.com/reg"},
                )
            ],
        ),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "all_have_default_api_key",
        lambda db, ids: _async_return(True),
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

    with pytest.raises(HTTPException) as excinfo:
        await server_module.register_lti_instance(request, data)

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid registration endpoint URL hostname"


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
        SimpleNamespace(
            url=lambda path: f"https://tool.example.com{path}",
            lti=config_module.config.lti,
        ),
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
async def test_lti_login_rejects_missing_authorization_endpoint(monkeypatch):
    registration = _make_registration(auth_login_url=None)
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
        SimpleNamespace(
            url=lambda path: f"https://tool.example.com{path}",
            lti=config_module.config.lti,
        ),
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

    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_login(request)

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "No known OIDC authorization endpoint for issuer"


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
        SimpleNamespace(
            url=lambda path: f"https://tool.example.com{path}",
            lti=config_module.config.lti,
        ),
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
async def test_lti_launch_rejects_invalid_context_memberships_url(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        server_module.LTI_CLAIM_CUSTOM_KEY: {
            "canvas_course_id": "course-1",
            "sso_provider_id": "0",
        },
        server_module.LTI_CLAIM_ROLES_KEY: [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
        ],
        server_module.LTI_CLAIM_NRPS_KEY: {
            "context_memberships_url": "not-a-url",
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
        canvas_module,
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

    state = _make_request_state()
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=state,
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid context_memberships_url"
    assert not any(isinstance(obj, FakeLTIClass) for obj in state.db.added)


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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
async def test_lti_launch_harvard_lxp_existing_lti_class_add_user(monkeypatch):
    from pingpong.lti.platforms import harvard_lxp as lxp_module

    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    registration.lms_platform = LMSPlatform.HARVARD_LXP
    linked_class = SimpleNamespace(
        id=99,
        lms_user_id=10,
        lms_course_id="course-1",
        lms_tenant=None,
        lms_type=None,
    )
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        server_module.LTI_CLAIM_CUSTOM_KEY: {"sso_provider_id": "0"},
        server_module.LTI_CLAIM_CONTEXT_KEY: {
            "id": "course-1",
            "title": "Learning Experience Showcase",
        },
        server_module.LTI_CLAIM_ROLES_KEY: [
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
        lxp_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(linked_class),
    )

    captured: dict[str, object] = {}

    class FakeAddUsers:
        def __init__(self, *args, **kwargs):
            captured["new_ucr"] = args[1]

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
    assert response.headers["location"].endswith("/group/99?lti_session=token")
    assert captured["new_ucr"].lms_type == LMSType.HARVARD_LXP


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
        canvas_module,
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
        canvas_module,
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
async def test_lti_launch_resume_unlinked_linked_lti_class(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    unlinked_class = FakeLTIClass(
        lti_status=LTIStatus.LINKED,
        class_id=None,
        setup_user_id=12,
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
        canvas_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(unlinked_class),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)

    class FakeAddUsers:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "AddNewUsersManual should not be called for unlinked LTI classes"
            )

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
    assert "/lti/setup" in response.headers["location"]
    assert unlinked_class.lti_status == LTIStatus.PENDING
    assert unlinked_class.setup_user_id == 42


@pytest.mark.asyncio
async def test_lti_launch_unlinked_class_from_other_registration_creates_new_pending(
    monkeypatch,
):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED,
        enabled=True,
        canvas_account_lti_guid="acct-guid-current",
    )
    stale_other_registration_class = FakeLTIClass(
        registration_id=99,
        lti_status=LTIStatus.LINKED,
        class_id=None,
        setup_user_id=12,
    )
    stale_other_registration_class.id = 999
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
        canvas_module,
        "find_class_by_course_id_search_by_canvas_account_lti_guid",
        lambda *args, **kwargs: _async_return(stale_other_registration_class),
    )
    monkeypatch.setattr(
        canvas_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(None),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)

    class FakeAddUsers:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "AddNewUsersManual should not be called when setup is required"
            )

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
    assert response.headers["location"].endswith(
        "/lti/setup?lti_session=token&lti_class_id=555"
    )
    assert stale_other_registration_class.lti_status == LTIStatus.LINKED
    assert stale_other_registration_class.setup_user_id == 12


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
        canvas_module,
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

    async def _create_or_update(
        db,
        user_id,
        provider,
        identifier,
        called_by=None,
        replace_existing=True,
    ):
        called["create_or_update"].append(
            {
                "provider": provider,
                "identifier": identifier,
                "user_id": user_id,
                "called_by": called_by,
                "replace_existing": replace_existing,
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
    assert called["create_or_update"][0]["replace_existing"] is False
    assert called["create_or_update"][1]["provider"] == "saml"
    assert called["create_or_update"][1]["replace_existing"] is True
    assert called["merge"] == [(user.id, 9999)]


@pytest.mark.asyncio
async def test_lti_launch_ambiguous_lookup_returns_conflict(monkeypatch):
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
        canvas_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(None),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)

    user = FakeUserModel("user@example.com")
    sso_provider = SimpleNamespace(id=5, name="saml")
    calls = {"lookups": []}

    async def _get_by_email_external_logins_priority(db, email, lookup_items):
        calls["lookups"].append(lookup_items)
        if len(calls["lookups"]) == 1:
            raise server_module.AmbiguousExternalLoginLookupError(
                lookup_index=0,
                lookup_item=lookup_items[0],
                user_ids=[123, 456],
            )
        return user, [user.id]

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
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )

    with pytest.raises(HTTPException) as exc_info:
        await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert exc_info.value.status_code == 409
    assert "Ambiguous external identity lookup" in exc_info.value.detail
    assert len(calls["lookups"]) == 1
    assert len(calls["lookups"][0]) == 3


@pytest.mark.asyncio
async def test_lti_launch_updates_email_after_merge(monkeypatch):
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
        "email": "new@example.com",
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
        canvas_module,
        "find_class_by_course_id",
        lambda *args, **kwargs: _async_return(None),
    )
    monkeypatch.setattr(server_module, "LTIClass", FakeLTIClass)

    user = FakeUserModel("old@example.com")
    merge_state = {"called": False}

    class MergeAwareDB(FakeDB):
        async def flush(self):
            # Simulate uniqueness conflict when the new email is flushed
            # before account merge resolves ownership.
            if user.email == "new@example.com" and not merge_state["called"]:
                raise AssertionError("email updated before merge")
            await super().flush()

    async def _get_by_email_external_logins_priority(db, email, lookup_items):
        return user, [user.id, 9999]

    async def _merge(db, authz, new_user_id, old_user_id):
        merge_state["called"] = True

    monkeypatch.setattr(server_module, "User", FakeUserModel)
    monkeypatch.setattr(
        server_module.User,
        "get_by_email_external_logins_priority",
        _get_by_email_external_logins_priority,
    )
    monkeypatch.setattr(server_module, "merge", _merge)
    monkeypatch.setattr(
        server_module, "encode_session_token", lambda user_id, nowfn: "token"
    )
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=_make_request_state(db=MergeAwareDB()),
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert "/lti/setup" in response.headers["location"]
    assert merge_state["called"] is True
    assert user.email == "new@example.com"


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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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
        canvas_module,
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


# --------------------------------------------------------------------------- #
# Harvard LXP platform-specific tests                                         #
# --------------------------------------------------------------------------- #


def _lxp_openid_payload():
    return {
        "issuer": "issuer",
        "authorization_endpoint": "https://platform.example.com/auth",
        "registration_endpoint": "https://platform.example.com/reg",
        "jwks_uri": "https://platform.example.com/jwks",
        "token_endpoint": "https://platform.example.com/token",
        "scopes_supported": server_module.REQUIRED_SCOPES,
        "id_token_signing_alg_values_supported": ["RS256"],
        "subject_types_supported": ["public"],
        server_module.PLATFORM_CONFIGURATION_KEY: {
            "product_family_code": "harvard_lxp",
            "messages_supported": [{"type": "LtiResourceLinkRequest"}],
        },
    }


@pytest.mark.asyncio
async def test_register_lti_instance_harvard_lxp_success(monkeypatch):
    openid_payload = _lxp_openid_payload()
    registration_payload = {"client_id": "client"}

    fake_factory = _fake_session_factory(
        get_payload=openid_payload, post_payload=registration_payload
    )
    sessions: list = []

    def _factory(*args, **kwargs):
        session = fake_factory(*args, **kwargs)
        sessions.append(session)
        return session

    monkeypatch.setattr(server_module.aiohttp, "ClientSession", _factory)
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
            lti=config_module.config.lti,
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
    assert created["data"]["lms_platform"] == LMSPlatform.HARVARD_LXP
    assert "canvas_account_name" not in created["data"]
    assert "canvas_account_lti_guid" not in created["data"]

    post_calls = [call for session in sessions for call in session.post_calls]
    assert post_calls, "expected POST to registration_endpoint"
    posted_payload = post_calls[0][1]["json"]
    serialized = json.dumps(posted_payload)
    assert "$Canvas" not in serialized
    assert "canvas_course_id" not in serialized
    assert "canvas_term_name" not in serialized
    assert "https://canvas.instructure.com/lti/vendor" not in serialized
    tool_config = posted_payload[
        "https://purl.imsglobal.org/spec/lti-tool-configuration"
    ]
    assert tool_config["custom_parameters"]["platform"] == "harvard_lxp"
    assert "sso_provider_id" not in tool_config["custom_parameters"]


@pytest.mark.asyncio
async def test_register_lti_instance_harvard_lxp_rejects_sso(monkeypatch):
    openid_payload = _lxp_openid_payload()

    monkeypatch.setattr(
        server_module.aiohttp,
        "ClientSession",
        _fake_session_factory(get_payload=openid_payload),
    )
    monkeypatch.setattr(
        server_module.Institution,
        "all_have_default_api_key",
        lambda db, ids: _async_return(True),
    )
    monkeypatch.setattr(
        server_module,
        "config",
        SimpleNamespace(
            url=lambda path: f"https://tool.example.com{path}",
            public_url="https://tool.example.com",
            email=SimpleNamespace(sender="sender"),
            lti=config_module.config.lti,
        ),
    )

    data = LTIRegisterRequest(
        name="PingPong",
        admin_name="Admin",
        admin_email="admin@example.com",
        provider_id=5,
        sso_field="person.sourcedId",
        openid_configuration="https://platform.example.com/.well-known/openid",
        registration_token="token",
        institution_ids=[1],
    )
    request = FakeRequest(state=SimpleNamespace(db="db"))

    with pytest.raises(HTTPException) as excinfo:
        await server_module.register_lti_instance(request, data)

    assert excinfo.value.status_code == 400
    assert "SSO-linked" in excinfo.value.detail


@pytest.mark.asyncio
async def test_lti_launch_harvard_lxp_missing_context_id(monkeypatch):
    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    registration.lms_platform = LMSPlatform.HARVARD_LXP
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        server_module.LTI_CLAIM_CUSTOM_KEY: {},
        server_module.LTI_CLAIM_CONTEXT_KEY: {"title": "Some Course"},
        server_module.LTI_CLAIM_ROLES_KEY: [
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
        server_module, "get_now_fn", lambda request: lambda: datetime.now(timezone.utc)
    )

    request = FakeRequest(
        payload={"state": "state", "id_token": "token"}, state=_make_request_state()
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.lti_launch(request, tasks=SimpleNamespace())
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Missing or invalid course_id"


@pytest.mark.asyncio
async def test_lti_launch_harvard_lxp_pending_setup(monkeypatch):
    from pingpong.lti.platforms import harvard_lxp as lxp_module

    oidc_session = _make_oidc_session(
        redirect_uri=server_module.config.url("/api/v1/lti/launch")
    )
    registration = _make_registration(
        review_status=LTIRegistrationReviewStatus.APPROVED, enabled=True
    )
    registration.lms_platform = LMSPlatform.HARVARD_LXP
    course_section_id = "39b59151-4bcb-4b17-a4f1-c4c8669a6a80"
    claims = {
        "nonce": "nonce",
        "email": "user@example.com",
        "given_name": "Evangelos",
        "family_name": "Kassos",
        server_module.LTI_CLAIM_CUSTOM_KEY: {},
        server_module.LTI_CLAIM_CONTEXT_KEY: {
            "id": course_section_id,
            "title": "Learning Experience Showcase",
            "label": "LES-" + course_section_id,
        },
        server_module.LTI_CLAIM_ROLES_KEY: [
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
        lxp_module,
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

    state = _make_request_state()
    request = FakeRequest(
        payload={"state": "state", "id_token": "token"},
        state=state,
    )

    response = await server_module.lti_launch(request, tasks=SimpleNamespace())

    assert response.status_code == 302
    assert "/lti/setup" in response.headers["location"]

    created = [obj for obj in state.db.added if isinstance(obj, FakeLTIClass)]
    assert len(created) == 1
    pending = created[0]
    assert pending.lti_platform == LMSPlatform.HARVARD_LXP
    assert pending.course_id == course_section_id
    assert pending.course_name == "Learning Experience Showcase"
    assert pending.course_code is None
    assert pending.course_term is None
    assert pending.lti_status == LTIStatus.PENDING

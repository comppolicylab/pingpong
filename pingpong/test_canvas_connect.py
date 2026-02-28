from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from pingpong.lti import canvas_connect as canvas_connect_module


class FakeTokenResponse:
    def __init__(
        self, *, status: int = 200, payload=None, text: str = "", headers=None
    ):
        self.status = status
        self._payload = payload
        self._text = text
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    async def text(self):
        return self._text


class FakeClientSession:
    def __init__(self, response: FakeTokenResponse | list[FakeTokenResponse]):
        if isinstance(response, list):
            self.responses = list(response)
        else:
            self.responses = [response]
        self.requests: list[dict] = []
        self.closed = False

    def post(self, url: str, *, headers: dict, data: dict):
        self.requests.append(
            {
                "method": "POST",
                "url": url,
                "headers": headers,
                "data": data,
            }
        )
        if not self.responses:
            raise AssertionError("No fake responses configured")
        return self.responses.pop(0)

    def get(self, url: str, *, headers: dict):
        self.requests.append(
            {
                "method": "GET",
                "url": url,
                "headers": headers,
            }
        )
        if not self.responses:
            raise AssertionError("No fake responses configured")
        return self.responses.pop(0)

    async def close(self):
        self.closed = True


class FakeKeyManager:
    async def get_current_key(self):
        return SimpleNamespace(
            kid="latest-kid",
            private_key_pem="private-key",
            algorithm="RS256",
        )


class FakeWriteDB:
    def __init__(self):
        self.added = []
        self.flush_count = 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flush_count += 1


class FakeSSOProvider:
    def __init__(self, name: str):
        self.name = name


@pytest.fixture(autouse=True)
def _allowlisted_platform_hosts(monkeypatch):
    assert canvas_connect_module.config.lti is not None
    monkeypatch.setattr(
        canvas_connect_module.config.lti,
        "platform_url_allowlist",
        [
            "canvas.example.com",
            "fallback.example.com",
            "platform.example.com",
            "tool.example.com",
        ],
    )


@pytest.mark.asyncio
async def test_get_nrps_access_token_uses_oidc_token_endpoint_and_signed_assertion(
    monkeypatch,
):
    token_endpoint = "https://canvas.example.com/login/oauth2/token"
    registration = SimpleNamespace(
        client_id="client-123",
        openid_configuration=f'{{"token_endpoint":"{token_endpoint}"}}',
        auth_token_url="https://fallback.example.com/token",
    )
    lti_class = SimpleNamespace(id=11, registration=registration)

    async def _get_by_id_with_registration(cls, db, id_):
        assert id_ == 11
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    jwt_calls: dict = {}

    def _encode(payload, private_key_pem, algorithm, headers):
        jwt_calls["payload"] = payload
        jwt_calls["private_key_pem"] = private_key_pem
        jwt_calls["algorithm"] = algorithm
        jwt_calls["headers"] = headers
        return "signed-client-assertion"

    monkeypatch.setattr(canvas_connect_module.jwt, "encode", _encode)
    monkeypatch.setattr(canvas_connect_module.uuid, "uuid7", lambda: "uuid7-test")

    fake_response = FakeTokenResponse(
        payload={
            "access_token": "short-lived-token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": canvas_connect_module.NRPS_CONTEXT_MEMBERSHIP_SCOPE,
        }
    )
    fake_session = FakeClientSession(fake_response)
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    fixed_now = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    async with canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=11,
        key_manager=FakeKeyManager(),
        nowfn=lambda: fixed_now,
    ) as client:
        token = await client.get_nrps_access_token()

    assert token.access_token == "short-lived-token"
    assert token.expires_in == 3600
    assert token.token_type == "Bearer"
    assert token.scope == canvas_connect_module.NRPS_CONTEXT_MEMBERSHIP_SCOPE
    assert fake_session.closed is True

    assert len(fake_session.requests) == 1
    req = fake_session.requests[0]
    assert req["url"] == token_endpoint
    assert req["headers"] == {
        "Content-Type": canvas_connect_module.TOKEN_REQUEST_CONTENT_TYPE
    }
    assert req["data"] == {
        "client_id": "client-123",
        "client_assertion_type": canvas_connect_module.CLIENT_ASSERTION_TYPE,
        "grant_type": canvas_connect_module.CLIENT_CREDENTIALS_GRANT_TYPE,
        "client_assertion": "signed-client-assertion",
        "scope": canvas_connect_module.NRPS_CONTEXT_MEMBERSHIP_SCOPE,
    }

    expected_iat = int(fixed_now.timestamp())
    expected_exp = int(
        (
            fixed_now
            + timedelta(seconds=canvas_connect_module.CLIENT_ASSERTION_EXPIRY_SECONDS)
        ).timestamp()
    )
    assert jwt_calls["payload"] == {
        "iss": "client-123",
        "sub": "client-123",
        "aud": token_endpoint,
        "iat": expected_iat,
        "exp": expected_exp,
        "jti": "uuid7-test",
    }
    assert jwt_calls["private_key_pem"] == "private-key"
    assert jwt_calls["algorithm"] == "RS256"
    assert jwt_calls["headers"] == {
        "typ": "JWT",
        "alg": "RS256",
        "kid": "latest-kid",
    }


@pytest.mark.asyncio
async def test_get_nrps_access_token_falls_back_to_registration_auth_token_url(
    monkeypatch,
):
    fallback_token_endpoint = "https://canvas.example.com/fallback/token"
    registration = SimpleNamespace(
        client_id="client-123",
        openid_configuration=None,
        auth_token_url=fallback_token_endpoint,
    )
    lti_class = SimpleNamespace(id=12, registration=registration)

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )
    monkeypatch.setattr(
        canvas_connect_module.jwt,
        "encode",
        lambda *args, **kwargs: "signed-client-assertion",
    )
    monkeypatch.setattr(canvas_connect_module.uuid, "uuid7", lambda: "uuid7-test")

    fake_session = FakeClientSession(
        FakeTokenResponse(payload={"access_token": "short-lived-token"})
    )
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    async with canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=12,
        key_manager=FakeKeyManager(),
        nowfn=lambda: datetime.now(timezone.utc),
    ) as client:
        token = await client.get_nrps_access_token()

    assert token.access_token == "short-lived-token"
    assert fake_session.requests[0]["url"] == fallback_token_endpoint


@pytest.mark.asyncio
async def test_get_nrps_access_token_raises_on_token_endpoint_error(monkeypatch):
    registration = SimpleNamespace(
        client_id="client-123",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(id=13, registration=registration)

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )
    monkeypatch.setattr(
        canvas_connect_module.jwt,
        "encode",
        lambda *args, **kwargs: "signed-client-assertion",
    )
    monkeypatch.setattr(canvas_connect_module.uuid, "uuid7", lambda: "uuid7-test")

    fake_session = FakeClientSession(
        FakeTokenResponse(
            status=401,
            payload={"error_description": "invalid client assertion"},
        )
    )
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    async with canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=13,
        key_manager=FakeKeyManager(),
        nowfn=lambda: datetime.now(timezone.utc),
    ) as client:
        with pytest.raises(canvas_connect_module.CanvasConnectException) as excinfo:
            await client.get_nrps_access_token()

    assert excinfo.value.detail == "invalid client assertion"


@pytest.mark.asyncio
async def test_get_nrps_access_token_raises_when_lti_class_missing(monkeypatch):
    async def _get_by_id_with_registration(cls, db, id_):
        return None

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    fake_session = FakeClientSession(
        FakeTokenResponse(payload={"access_token": "unused"})
    )
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    async with canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=404,
        key_manager=FakeKeyManager(),
    ) as client:
        with pytest.raises(canvas_connect_module.CanvasConnectException) as excinfo:
            await client.get_nrps_access_token()

    assert excinfo.value.detail == "LTI class not found"


@pytest.mark.asyncio
async def test_get_nrps_access_token_reuses_cached_token_until_expiry(monkeypatch):
    token_endpoint = "https://canvas.example.com/login/oauth2/token"
    registration = SimpleNamespace(
        client_id="client-123",
        openid_configuration=f'{{"token_endpoint":"{token_endpoint}"}}',
        auth_token_url="https://fallback.example.com/token",
    )
    lti_class = SimpleNamespace(id=14, registration=registration)

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )
    monkeypatch.setattr(
        canvas_connect_module.jwt,
        "encode",
        lambda *args, **kwargs: "signed-client-assertion",
    )
    monkeypatch.setattr(canvas_connect_module.uuid, "uuid7", lambda: "uuid7-test")

    fake_session = FakeClientSession(
        FakeTokenResponse(
            payload={
                "access_token": "cached-token",
                "expires_in": 3600,
            }
        )
    )
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    fixed_now = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    async with canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=14,
        key_manager=FakeKeyManager(),
        nowfn=lambda: fixed_now,
    ) as client:
        token_one = await client.get_nrps_access_token()
        token_two = await client.get_nrps_access_token()

    assert token_one.access_token == "cached-token"
    assert token_two.access_token == "cached-token"
    assert len(fake_session.requests) == 1


@pytest.mark.asyncio
async def test_get_nrps_access_token_refreshes_when_cached_token_expired(monkeypatch):
    token_endpoint = "https://canvas.example.com/login/oauth2/token"
    registration = SimpleNamespace(
        client_id="client-123",
        openid_configuration=f'{{"token_endpoint":"{token_endpoint}"}}',
        auth_token_url="https://fallback.example.com/token",
    )
    lti_class = SimpleNamespace(id=15, registration=registration)

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )
    monkeypatch.setattr(
        canvas_connect_module.jwt,
        "encode",
        lambda *args, **kwargs: "signed-client-assertion",
    )
    monkeypatch.setattr(canvas_connect_module.uuid, "uuid7", lambda: "uuid7-test")

    fake_session = FakeClientSession(
        [
            FakeTokenResponse(
                payload={
                    "access_token": "token-one",
                    "expires_in": 120,
                }
            ),
            FakeTokenResponse(
                payload={
                    "access_token": "token-two",
                    "expires_in": 120,
                }
            ),
        ]
    )
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    now_holder = {"value": datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)}

    async with canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=15,
        key_manager=FakeKeyManager(),
        nowfn=lambda: now_holder["value"],
    ) as client:
        token_one = await client.get_nrps_access_token()
        now_holder["value"] = now_holder["value"] + timedelta(seconds=200)
        token_two = await client.get_nrps_access_token()

    assert token_one.access_token == "token-one"
    assert token_two.access_token == "token-two"
    assert len(fake_session.requests) == 2


@pytest.mark.asyncio
async def test_get_context_memberships_url_returns_saved_value(monkeypatch):
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=16,
        registration=registration,
        context_memberships_url="https://canvas.example.com/memberships",
        course_id="123",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    client = canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=16,
        key_manager=FakeKeyManager(),
    )
    memberships_url = await client.get_context_memberships_url()

    assert memberships_url == "https://canvas.example.com/memberships"


@pytest.mark.asyncio
async def test_get_context_memberships_url_raises_when_missing(monkeypatch):
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=17,
        registration=registration,
        context_memberships_url=None,
        course_id="123",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    client = canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=17,
        key_manager=FakeKeyManager(),
    )
    with pytest.raises(canvas_connect_module.CanvasConnectException) as excinfo:
        await client.get_context_memberships_url()

    assert excinfo.value.detail == "LTI class is missing context_memberships_url"


@pytest.mark.asyncio
async def test_get_context_memberships_url_raises_when_host_is_not_allowed(monkeypatch):
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        auth_login_url="https://canvas.example.com/login",
        key_set_url="https://canvas.example.com/jwks",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=1701,
        registration=registration,
        context_memberships_url="https://evil.example.com/memberships",
        course_id="123",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    client = canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=1701,
        key_manager=FakeKeyManager(),
    )
    with pytest.raises(canvas_connect_module.CanvasConnectException) as excinfo:
        await client.get_context_memberships_url()

    assert (
        excinfo.value.detail
        == "context_memberships_url host is not allowed for this registration"
    )


@pytest.mark.asyncio
async def test_get_context_memberships_url_raises_when_host_is_not_allowlisted(
    monkeypatch,
):
    monkeypatch.setattr(
        canvas_connect_module.config.lti,
        "platform_url_allowlist",
        ["tool.example.com"],
    )
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        auth_login_url="https://canvas.example.com/login",
        key_set_url="https://canvas.example.com/jwks",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=1702,
        registration=registration,
        context_memberships_url="https://canvas.example.com/memberships",
        course_id="123",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    client = canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=1702,
        key_manager=FakeKeyManager(),
    )
    with pytest.raises(canvas_connect_module.CanvasConnectException) as excinfo:
        await client.get_context_memberships_url()

    assert excinfo.value.detail == "context_memberships_url host is not allowlisted"


def test_registration_allowed_hosts_extracts_hosts_from_registration_urls():
    registration = SimpleNamespace(
        auth_login_url="https://evil.example.com/login",
        auth_token_url="https://canvas.example.com/token",
        key_set_url="https://evil.example.com/jwks",
        openid_configuration='{"authorization_endpoint":"https://evil.example.com/auth"}',
    )

    allowed_hosts = (
        canvas_connect_module.CanvasConnectClient._registration_allowed_hosts(
            registration
        )
    )

    assert allowed_hosts == {"canvas.example.com", "evil.example.com"}


@pytest.mark.asyncio
async def test_get_lti_class_is_cached_per_client_instance(monkeypatch):
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=18,
        registration=registration,
        context_memberships_url="https://canvas.example.com/memberships",
        course_id="123",
    )
    call_count = {"count": 0}

    async def _get_by_id_with_registration(cls, db, id_):
        call_count["count"] += 1
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    client = canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=18,
        key_manager=FakeKeyManager(),
    )
    first = await client.get_context_memberships_url()
    second = await client.get_context_memberships_url()

    assert first == "https://canvas.example.com/memberships"
    assert second == "https://canvas.example.com/memberships"
    assert call_count["count"] == 1


@pytest.mark.asyncio
async def test_get_resource_link_id_returns_existing_without_fetch(monkeypatch):
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=19,
        registration=registration,
        context_memberships_url="https://canvas.example.com/api/lti/courses/1/names_and_roles",
        resource_link_id="existing-resource-link-id",
        course_id="1",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )
    fake_session = FakeClientSession([])
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    async with canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=19,
        key_manager=FakeKeyManager(),
    ) as client:
        resource_link_id = await client.get_resource_link_id()

    assert resource_link_id == "existing-resource-link-id"
    assert fake_session.requests == []


@pytest.mark.asyncio
async def test_get_resource_link_id_returns_none_when_missing(monkeypatch):
    context_memberships_url = (
        "https://canvas.example.com/api/lti/courses/1/names_and_roles"
    )
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=20,
        registration=registration,
        context_memberships_url=context_memberships_url,
        resource_link_id=None,
        course_id="1",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )
    fake_session = FakeClientSession([])
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    db = FakeWriteDB()
    async with canvas_connect_module.CanvasConnectClient(
        db=db,
        lti_class_id=20,
        key_manager=FakeKeyManager(),
        nowfn=lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
    ) as client:
        resource_link_id = await client.get_resource_link_id()

    assert resource_link_id is None
    assert lti_class.resource_link_id is None
    assert db.added == []
    assert db.flush_count == 0
    assert fake_session.requests == []


@pytest.mark.asyncio
async def test_get_resource_link_id_uses_nrps_context_id_as_transient_fallback(
    monkeypatch,
):
    token_endpoint = "https://canvas.example.com/login/oauth2/token"
    context_memberships_url = (
        "https://canvas.example.com/api/lti/courses/1/names_and_roles"
    )
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration=f'{{"token_endpoint":"{token_endpoint}"}}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=2001,
        registration=registration,
        context_memberships_url=context_memberships_url,
        resource_link_id=None,
        course_id="1",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )
    monkeypatch.setattr(
        canvas_connect_module.jwt,
        "encode",
        lambda *args, **kwargs: "signed-client-assertion",
    )
    monkeypatch.setattr(canvas_connect_module.uuid, "uuid7", lambda: "uuid7-test")

    fake_session = FakeClientSession(
        [
            FakeTokenResponse(
                payload={
                    "access_token": "short-lived-token",
                    "expires_in": 3600,
                }
            ),
            FakeTokenResponse(
                payload={
                    "context": {
                        "id": "transient-resource-link-id",
                    }
                }
            ),
        ]
    )
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    db = FakeWriteDB()
    async with canvas_connect_module.CanvasConnectClient(
        db=db,
        lti_class_id=2001,
        key_manager=FakeKeyManager(),
        nowfn=lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
    ) as client:
        resource_link_id = await client.get_resource_link_id(
            allow_nrps_context_fallback=True
        )

    assert resource_link_id == "transient-resource-link-id"
    assert lti_class.resource_link_id is None
    assert db.added == []
    assert db.flush_count == 0
    assert len(fake_session.requests) == 2
    assert fake_session.requests[1]["method"] == "GET"
    assert fake_session.requests[1]["url"] == context_memberships_url


@pytest.mark.asyncio
async def test_get_nrps_create_user_class_roles_maps_members_and_pages(monkeypatch):
    token_endpoint = "https://canvas.example.com/login/oauth2/token"
    context_memberships_url = (
        "https://canvas.example.com/api/lti/courses/1/names_and_roles"
    )
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration=f'{{"token_endpoint":"{token_endpoint}"}}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=21,
        registration=registration,
        context_memberships_url=context_memberships_url,
        resource_link_id="resource-link-id",
        course_id="1",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )
    monkeypatch.setattr(
        canvas_connect_module.ExternalLoginProvider,
        "get_by_id",
        classmethod(lambda cls, db, id_: _async_return(FakeSSOProvider("my-sso"))),
    )
    monkeypatch.setattr(
        canvas_connect_module.jwt,
        "encode",
        lambda *args, **kwargs: "signed-client-assertion",
    )
    monkeypatch.setattr(canvas_connect_module.uuid, "uuid7", lambda: "uuid7-test")

    fake_session = FakeClientSession(
        [
            FakeTokenResponse(
                payload={
                    "access_token": "short-lived-token",
                    "expires_in": 3600,
                }
            ),
            FakeTokenResponse(
                payload={
                    "members": [
                        {
                            "status": "Active",
                            "name": "Instructor One",
                            "email": "instructor@example.com",
                            "roles": [
                                "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
                            ],
                            "message": [
                                {
                                    "https://purl.imsglobal.org/spec/lti/claim/custom": {
                                        "sso_value": "111",
                                        "sso_provider_id": "7",
                                    }
                                }
                            ],
                        },
                        {
                            "status": "Active",
                            "name": "Student One",
                            "email": "student@example.com",
                            "roles": [
                                "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
                            ],
                            "message": [
                                {
                                    "https://purl.imsglobal.org/spec/lti/claim/custom": {
                                        "sso_value": "222",
                                        "sso_provider_id": "7",
                                    }
                                }
                            ],
                        },
                        {
                            "status": "Inactive",
                            "name": "Inactive User",
                            "email": "inactive@example.com",
                            "roles": [
                                "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
                            ],
                        },
                    ],
                    "next": f"{context_memberships_url}?rlid=resource-link-id&page=2",
                }
            ),
            FakeTokenResponse(
                payload={
                    "members": [
                        {
                            "status": "Active",
                            "name": "Student Promoted",
                            "email": "student@example.com",
                            "roles": [
                                "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
                            ],
                            "message": [
                                {
                                    "https://purl.imsglobal.org/spec/lti/claim/custom": {
                                        "sso_value": "222",
                                        "sso_provider_id": "7",
                                    }
                                }
                            ],
                        },
                        {
                            "status": "Active",
                            "name": "Admin One",
                            "email": "admin@example.com",
                            "roles": [
                                "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"
                            ],
                        },
                    ]
                }
            ),
        ]
    )
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    async with canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=21,
        key_manager=FakeKeyManager(),
        nowfn=lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
    ) as client:
        create_roles = await client.get_nrps_create_user_class_roles()

    assert create_roles.silent is True
    assert create_roles.lti_class_id == 21
    assert create_roles.lms_type == canvas_connect_module.LMSType.CANVAS
    assert create_roles.sso_tenant == "my-sso"
    assert len(create_roles.roles) == 3

    by_email = {role.email: role for role in create_roles.roles}
    assert set(by_email.keys()) == {
        "instructor@example.com",
        "student@example.com",
        "admin@example.com",
    }
    assert by_email[
        "instructor@example.com"
    ].roles == canvas_connect_module.ClassUserRoles(
        admin=False, teacher=True, student=False
    )
    assert by_email["instructor@example.com"].sso_id == "111"
    assert by_email[
        "student@example.com"
    ].roles == canvas_connect_module.ClassUserRoles(
        admin=False, teacher=True, student=False
    )
    assert by_email["student@example.com"].sso_id == "222"
    assert by_email["admin@example.com"].roles == canvas_connect_module.ClassUserRoles(
        admin=True, teacher=False, student=False
    )
    assert by_email["admin@example.com"].sso_id is None

    assert len(fake_session.requests) == 3
    assert fake_session.requests[0]["method"] == "POST"
    assert fake_session.requests[1]["method"] == "GET"
    assert fake_session.requests[2]["method"] == "GET"
    assert (
        fake_session.requests[1]["url"]
        == f"{context_memberships_url}?rlid=resource-link-id"
    )


@pytest.mark.asyncio
async def test_get_nrps_create_user_class_roles_rejects_untrusted_next_page(
    monkeypatch,
):
    token_endpoint = "https://canvas.example.com/login/oauth2/token"
    context_memberships_url = (
        "https://canvas.example.com/api/lti/courses/1/names_and_roles"
    )
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        auth_login_url="https://canvas.example.com/login",
        key_set_url="https://canvas.example.com/jwks",
        openid_configuration=f'{{"token_endpoint":"{token_endpoint}"}}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=2101,
        registration=registration,
        context_memberships_url=context_memberships_url,
        resource_link_id="resource-link-id",
        course_id="1",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )
    monkeypatch.setattr(
        canvas_connect_module.jwt,
        "encode",
        lambda *args, **kwargs: "signed-client-assertion",
    )
    monkeypatch.setattr(canvas_connect_module.uuid, "uuid7", lambda: "uuid7-test")

    fake_session = FakeClientSession(
        [
            FakeTokenResponse(
                payload={
                    "access_token": "short-lived-token",
                    "expires_in": 3600,
                }
            ),
            FakeTokenResponse(
                payload={
                    "members": [],
                    canvas_connect_module.NRPS_NEXT_PAGE_KEY: "https://evil.example.com/next",
                }
            ),
        ]
    )
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    async with canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=2101,
        key_manager=FakeKeyManager(),
        nowfn=lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
    ) as client:
        with pytest.raises(canvas_connect_module.CanvasConnectException) as excinfo:
            await client.get_nrps_create_user_class_roles()

    assert (
        excinfo.value.detail
        == "nrps_page_url host is not allowed for this registration"
    )
    assert len(fake_session.requests) == 2
    assert fake_session.requests[1]["method"] == "GET"


@pytest.mark.asyncio
async def test_get_nrps_create_user_class_roles_allows_missing_members(monkeypatch):
    token_endpoint = "https://canvas.example.com/login/oauth2/token"
    context_memberships_url = (
        "https://canvas.example.com/api/lti/courses/1/names_and_roles"
    )
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration=f'{{"token_endpoint":"{token_endpoint}"}}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=22,
        registration=registration,
        context_memberships_url=context_memberships_url,
        resource_link_id=None,
        course_id="1",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )
    monkeypatch.setattr(
        canvas_connect_module.ExternalLoginProvider,
        "get_by_id",
        classmethod(lambda cls, db, id_: _async_return(None)),
    )
    monkeypatch.setattr(
        canvas_connect_module.jwt,
        "encode",
        lambda *args, **kwargs: "signed-client-assertion",
    )
    monkeypatch.setattr(canvas_connect_module.uuid, "uuid7", lambda: "uuid7-test")

    fake_session = FakeClientSession(
        [
            FakeTokenResponse(
                payload={
                    "access_token": "short-lived-token",
                    "expires_in": 3600,
                }
            ),
            FakeTokenResponse(payload={"context": {"id": "fallback-context-id"}}),
            FakeTokenResponse(payload={"id": context_memberships_url}),
        ]
    )
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    async with canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=22,
        key_manager=FakeKeyManager(),
        nowfn=lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
    ) as client:
        create_roles = await client.get_nrps_create_user_class_roles()

    assert create_roles.roles == []
    assert len(fake_session.requests) == 3
    assert fake_session.requests[1]["url"] == context_memberships_url
    assert (
        fake_session.requests[2]["url"]
        == f"{context_memberships_url}?rlid=fallback-context-id"
    )


async def _async_return(value):
    return value


@pytest.mark.asyncio
async def test_get_nrps_create_user_class_roles_no_sso_when_provider_id_zero(
    monkeypatch,
):
    token_endpoint = "https://canvas.example.com/login/oauth2/token"
    context_memberships_url = (
        "https://canvas.example.com/api/lti/courses/1/names_and_roles"
    )
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration=f'{{"token_endpoint":"{token_endpoint}"}}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=23,
        registration=registration,
        context_memberships_url=context_memberships_url,
        resource_link_id="resource-link-id",
        course_id="1",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )
    monkeypatch.setattr(
        canvas_connect_module.ExternalLoginProvider,
        "get_by_id",
        classmethod(
            lambda cls, db, id_: _async_return(FakeSSOProvider("should-not-be-used"))
        ),
    )
    monkeypatch.setattr(
        canvas_connect_module.jwt,
        "encode",
        lambda *args, **kwargs: "signed-client-assertion",
    )
    monkeypatch.setattr(canvas_connect_module.uuid, "uuid7", lambda: "uuid7-test")

    fake_session = FakeClientSession(
        [
            FakeTokenResponse(
                payload={
                    "access_token": "short-lived-token",
                    "expires_in": 3600,
                }
            ),
            FakeTokenResponse(
                payload={
                    "members": [
                        {
                            "status": "Active",
                            "name": "No SSO",
                            "email": "nossos@example.com",
                            "roles": [
                                "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
                            ],
                            "message": [
                                {
                                    "https://purl.imsglobal.org/spec/lti/claim/custom": {
                                        "sso_value": "",
                                        "sso_provider_id": "0",
                                    }
                                }
                            ],
                        }
                    ]
                }
            ),
        ]
    )
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    async with canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=23,
        key_manager=FakeKeyManager(),
        nowfn=lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
    ) as client:
        create_roles = await client.get_nrps_create_user_class_roles()

    assert create_roles.sso_tenant is None
    assert len(create_roles.roles) == 1
    assert create_roles.roles[0].email == "nossos@example.com"
    assert create_roles.roles[0].sso_id is None


@pytest.mark.asyncio
async def test_get_nrps_create_user_class_roles_ignores_sso_provider_ids_from_skipped_members(
    monkeypatch,
):
    token_endpoint = "https://canvas.example.com/login/oauth2/token"
    context_memberships_url = (
        "https://canvas.example.com/api/lti/courses/1/names_and_roles"
    )
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration=f'{{"token_endpoint":"{token_endpoint}"}}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=2301,
        registration=registration,
        context_memberships_url=context_memberships_url,
        resource_link_id="resource-link-id",
        course_id="1",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )
    monkeypatch.setattr(
        canvas_connect_module.ExternalLoginProvider,
        "get_by_id",
        classmethod(
            lambda cls, db, id_: _async_return(
                FakeSSOProvider("my-sso") if id_ == 7 else None
            )
        ),
    )
    monkeypatch.setattr(
        canvas_connect_module.jwt,
        "encode",
        lambda *args, **kwargs: "signed-client-assertion",
    )
    monkeypatch.setattr(canvas_connect_module.uuid, "uuid7", lambda: "uuid7-test")

    fake_session = FakeClientSession(
        [
            FakeTokenResponse(
                payload={
                    "access_token": "short-lived-token",
                    "expires_in": 3600,
                }
            ),
            FakeTokenResponse(
                payload={
                    "members": [
                        {
                            "status": "Inactive",
                            "name": "Inactive Learner",
                            "email": "inactive@example.com",
                            "roles": [
                                "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
                            ],
                            "message": [
                                {
                                    "https://purl.imsglobal.org/spec/lti/claim/custom": {
                                        "sso_value": "inactive-id",
                                        "sso_provider_id": "999",
                                    }
                                }
                            ],
                        },
                        {
                            "status": "Active",
                            "name": "Active Learner",
                            "email": "active@example.com",
                            "roles": [
                                "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
                            ],
                            "message": [
                                {
                                    "https://purl.imsglobal.org/spec/lti/claim/custom": {
                                        "sso_value": "active-id",
                                        "sso_provider_id": "7",
                                    }
                                }
                            ],
                        },
                    ]
                }
            ),
        ]
    )
    monkeypatch.setattr(
        canvas_connect_module.aiohttp,
        "ClientSession",
        lambda: fake_session,
    )

    async with canvas_connect_module.CanvasConnectClient(
        db=SimpleNamespace(),
        lti_class_id=2301,
        key_manager=FakeKeyManager(),
        nowfn=lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
    ) as client:
        create_roles = await client.get_nrps_create_user_class_roles()

    assert create_roles.sso_tenant == "my-sso"
    assert len(create_roles.roles) == 1
    assert create_roles.roles[0].email == "active@example.com"
    assert create_roles.roles[0].sso_id == "active-id"


@pytest.mark.asyncio
async def test_sync_calls_add_new_users_script_with_lti_class_context(monkeypatch):
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=24,
        registration=registration,
        class_id=321,
        setup_user_id=42,
        lti_status=canvas_connect_module.LTIStatus.ERROR,
        last_sync_error="old-error",
        last_synced=None,
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    expected_ucr = canvas_connect_module.CreateUserClassRoles(
        roles=[],
        silent=True,
        lms_type=canvas_connect_module.LMSType.CANVAS,
        lti_class_id=24,
    )

    async def _get_nrps_create_user_class_roles(self):
        return expected_ucr

    monkeypatch.setattr(
        canvas_connect_module.CanvasConnectClient,
        "get_nrps_create_user_class_roles",
        _get_nrps_create_user_class_roles,
    )

    captured: dict[str, object] = {}

    class FakeAddNewUsersScript:
        def __init__(self, class_id, user_id, session, client, new_ucr):
            captured["class_id"] = class_id
            captured["user_id"] = user_id
            captured["session"] = session
            captured["client"] = client
            captured["new_ucr"] = new_ucr

        async def add_new_users(self):
            return canvas_connect_module.CreateUserResults(
                results=[{"email": "synced@example.com"}]
            )

    monkeypatch.setattr(
        canvas_connect_module,
        "AddNewUsersScript",
        FakeAddNewUsersScript,
    )

    fixed_now = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    db = FakeWriteDB()
    authz_client = SimpleNamespace()
    client = canvas_connect_module.ScriptCanvasConnectClient(
        db=db,
        client=authz_client,
        lti_class_id=24,
        key_manager=FakeKeyManager(),
        nowfn=lambda: fixed_now,
    )
    result = await client.sync_roster()

    assert result == canvas_connect_module.CreateUserResults(
        results=[{"email": "synced@example.com"}]
    )
    assert captured["class_id"] == "321"
    assert captured["user_id"] == 42
    assert captured["session"] is db
    assert captured["client"] is authz_client
    assert captured["new_ucr"] is expected_ucr
    assert lti_class.lti_status == canvas_connect_module.LTIStatus.LINKED
    assert lti_class.last_sync_error is None
    assert lti_class.last_synced == fixed_now
    assert db.added == [lti_class]
    assert db.flush_count == 1


@pytest.mark.asyncio
async def test_sync_raises_when_lti_class_not_linked(monkeypatch):
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=25,
        registration=registration,
        class_id=None,
        setup_user_id=42,
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    client = canvas_connect_module.ScriptCanvasConnectClient(
        db=SimpleNamespace(),
        client=SimpleNamespace(),
        lti_class_id=25,
        key_manager=FakeKeyManager(),
    )

    with pytest.raises(canvas_connect_module.CanvasConnectException) as excinfo:
        await client.sync_roster()

    assert excinfo.value.detail == "LTI class is not linked to a PingPong class"


@pytest.mark.asyncio
async def test_sync_raises_when_lti_class_missing_setup_user_id(monkeypatch):
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    lti_class = SimpleNamespace(
        id=26,
        registration=registration,
        class_id=321,
        setup_user_id=None,
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    client = canvas_connect_module.ScriptCanvasConnectClient(
        db=SimpleNamespace(),
        client=SimpleNamespace(),
        lti_class_id=26,
        key_manager=FakeKeyManager(),
    )

    with pytest.raises(canvas_connect_module.CanvasConnectException) as excinfo:
        await client.sync_roster()

    assert excinfo.value.detail == "LTI class is missing setup_user_id"


@pytest.mark.asyncio
async def test_manual_canvas_connect_sync_roster_enforces_cooldown(monkeypatch):
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    fixed_now = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    lti_class = SimpleNamespace(
        id=27,
        registration=registration,
        class_id=321,
        setup_user_id=42,
        last_synced=fixed_now - timedelta(minutes=5),
        lti_status=canvas_connect_module.LTIStatus.LINKED,
        last_sync_error=None,
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    request = SimpleNamespace(state={"db": FakeWriteDB()})
    tasks = SimpleNamespace()
    client = canvas_connect_module.ManualCanvasConnectClient(
        lti_class_id=27,
        request=request,
        tasks=tasks,
        key_manager=FakeKeyManager(),
        nowfn=lambda: fixed_now,
    )

    with pytest.raises(canvas_connect_module.CanvasConnectWarning) as excinfo:
        await client.sync_roster()

    assert "recently completed" in excinfo.value.detail
    assert "\n" not in excinfo.value.detail
    assert (
        "Please wait before trying again. You can request a manual sync in "
        in excinfo.value.detail
    )


def test_manual_sync_uses_lti_config_sync_wait(monkeypatch):
    monkeypatch.setattr(
        canvas_connect_module.config,
        "lti",
        SimpleNamespace(sync_wait=321),
    )
    client = canvas_connect_module.ManualCanvasConnectClient(
        lti_class_id=1,
        request=SimpleNamespace(state={"db": FakeWriteDB()}),
        tasks=SimpleNamespace(),
        key_manager=FakeKeyManager(),
    )
    now = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)

    with pytest.raises(canvas_connect_module.CanvasConnectWarning):
        client._sync_allowed(now - timedelta(seconds=200), now)


def test_manual_sync_defaults_when_lti_config_missing(monkeypatch):
    monkeypatch.setattr(
        canvas_connect_module.config,
        "lti",
        None,
    )
    client = canvas_connect_module.ManualCanvasConnectClient(
        lti_class_id=1,
        request=SimpleNamespace(state={"db": FakeWriteDB()}),
        tasks=SimpleNamespace(),
        key_manager=FakeKeyManager(),
    )
    now = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)

    with pytest.raises(canvas_connect_module.CanvasConnectWarning):
        client._sync_allowed(now - timedelta(seconds=500), now)


@pytest.mark.asyncio
async def test_manual_canvas_connect_sync_roster_calls_add_new_users_manual(
    monkeypatch,
):
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    fixed_now = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    lti_class = SimpleNamespace(
        id=28,
        registration=registration,
        class_id=321,
        setup_user_id=42,
        last_synced=fixed_now - timedelta(minutes=30),
        lti_status=canvas_connect_module.LTIStatus.ERROR,
        last_sync_error="old-error",
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    expected_ucr = canvas_connect_module.CreateUserClassRoles(
        roles=[],
        silent=True,
        lms_type=canvas_connect_module.LMSType.CANVAS,
        lti_class_id=28,
    )

    async def _get_nrps_create_user_class_roles(self):
        return expected_ucr

    monkeypatch.setattr(
        canvas_connect_module.CanvasConnectClient,
        "get_nrps_create_user_class_roles",
        _get_nrps_create_user_class_roles,
    )

    captured: dict[str, object] = {}

    class FakeAddNewUsersManual:
        def __init__(self, class_id, new_ucr, request, tasks, user_id=None):
            captured["class_id"] = class_id
            captured["new_ucr"] = new_ucr
            captured["request"] = request
            captured["tasks"] = tasks
            captured["user_id"] = user_id

        async def add_new_users(self):
            return canvas_connect_module.CreateUserResults(
                results=[{"email": "synced@example.com"}]
            )

    monkeypatch.setattr(
        canvas_connect_module,
        "AddNewUsersManual",
        FakeAddNewUsersManual,
    )

    db = FakeWriteDB()
    request = SimpleNamespace(state={"db": db})
    tasks = SimpleNamespace()
    client = canvas_connect_module.ManualCanvasConnectClient(
        lti_class_id=28,
        request=request,
        tasks=tasks,
        key_manager=FakeKeyManager(),
        nowfn=lambda: fixed_now,
    )
    result = await client.sync_roster()

    assert result == canvas_connect_module.CreateUserResults(
        results=[{"email": "synced@example.com"}]
    )
    assert captured["class_id"] == "321"
    assert captured["new_ucr"] is expected_ucr
    assert captured["request"] is request
    assert captured["tasks"] is tasks
    assert captured["user_id"] == 42
    assert lti_class.lti_status == canvas_connect_module.LTIStatus.LINKED
    assert lti_class.last_sync_error is None
    assert lti_class.last_synced == fixed_now
    assert db.added == [lti_class]
    assert db.flush_count == 1


@pytest.mark.asyncio
async def test_manual_canvas_connect_sync_roster_raises_manual_error_on_failure(
    monkeypatch,
):
    registration = SimpleNamespace(
        client_id="client-123",
        issuer="https://canvas.example.com",
        openid_configuration='{"token_endpoint":"https://canvas.example.com/token"}',
        auth_token_url="https://canvas.example.com/fallback-token",
    )
    fixed_now = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    lti_class = SimpleNamespace(
        id=281,
        registration=registration,
        class_id=321,
        setup_user_id=42,
        last_synced=fixed_now - timedelta(minutes=30),
        lti_status=canvas_connect_module.LTIStatus.LINKED,
        last_sync_error=None,
    )

    async def _get_by_id_with_registration(cls, db, id_):
        return lti_class

    monkeypatch.setattr(
        canvas_connect_module.LTIClass,
        "get_by_id_with_registration",
        classmethod(_get_by_id_with_registration),
    )

    expected_ucr = canvas_connect_module.CreateUserClassRoles(
        roles=[],
        silent=True,
        lms_type=canvas_connect_module.LMSType.CANVAS,
        lti_class_id=281,
    )

    async def _get_nrps_create_user_class_roles(self):
        return expected_ucr

    monkeypatch.setattr(
        canvas_connect_module.CanvasConnectClient,
        "get_nrps_create_user_class_roles",
        _get_nrps_create_user_class_roles,
    )

    class FakeAddNewUsersManual:
        def __init__(self, class_id, new_ucr, request, tasks, user_id=None):
            pass

        async def add_new_users(self):
            raise RuntimeError("downstream-add-users-failure")

    monkeypatch.setattr(
        canvas_connect_module,
        "AddNewUsersManual",
        FakeAddNewUsersManual,
    )

    db = FakeWriteDB()
    request = SimpleNamespace(state={"db": db})
    tasks = SimpleNamespace()
    client = canvas_connect_module.ManualCanvasConnectClient(
        lti_class_id=281,
        request=request,
        tasks=tasks,
        key_manager=FakeKeyManager(),
        nowfn=lambda: fixed_now,
    )

    with pytest.raises(canvas_connect_module.CanvasConnectException) as excinfo:
        await client.sync_roster()

    assert "Canvas Connect" in excinfo.value.detail
    assert lti_class.lti_status == canvas_connect_module.LTIStatus.ERROR
    assert lti_class.last_sync_error == "downstream-add-users-failure"
    assert db.added == [lti_class]
    assert db.flush_count == 1


@pytest.mark.asyncio
async def test_script_canvas_connect_sync_roster_uses_script_client(monkeypatch):
    captured: dict[str, object] = {}
    fake_lti_class = SimpleNamespace(
        id=29,
        class_id=321,
        setup_user_id=42,
        lti_status=canvas_connect_module.LTIStatus.LINKED,
        last_sync_error=None,
        last_synced=None,
    )

    async def _get_sync_context(self):
        return fake_lti_class, 321, 42

    async def _get_nrps_create_user_class_roles(self):
        return canvas_connect_module.CreateUserClassRoles(
            roles=[],
            silent=True,
            lms_type=canvas_connect_module.LMSType.CANVAS,
            lti_class_id=29,
        )

    class FakeAddNewUsersScript:
        def __init__(self, class_id, user_id, session, client, new_ucr):
            captured["class_id"] = class_id
            captured["user_id"] = user_id
            captured["session"] = session
            captured["client"] = client
            captured["new_ucr"] = new_ucr

        async def add_new_users(self):
            return canvas_connect_module.CreateUserResults(
                results=[{"email": "synced@example.com"}]
            )

    monkeypatch.setattr(
        canvas_connect_module.CanvasConnectClient,
        "_get_sync_context",
        _get_sync_context,
    )
    monkeypatch.setattr(
        canvas_connect_module.CanvasConnectClient,
        "get_nrps_create_user_class_roles",
        _get_nrps_create_user_class_roles,
    )
    monkeypatch.setattr(
        canvas_connect_module,
        "AddNewUsersScript",
        FakeAddNewUsersScript,
    )

    db = FakeWriteDB()
    authz_client = SimpleNamespace()
    client = canvas_connect_module.ScriptCanvasConnectClient(
        db=db,
        client=authz_client,
        lti_class_id=29,
        key_manager=FakeKeyManager(),
        nowfn=lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
    )
    result = await client.sync_roster()

    assert result == canvas_connect_module.CreateUserResults(
        results=[{"email": "synced@example.com"}]
    )
    assert captured["class_id"] == "321"
    assert captured["user_id"] == 42
    assert captured["session"] is db
    assert captured["client"] is authz_client


@pytest.mark.asyncio
async def test_script_canvas_connect_sync_roster_marks_error_on_row_failures(
    monkeypatch,
):
    fixed_now = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    previous_sync = fixed_now - timedelta(hours=3)
    fake_lti_class = SimpleNamespace(
        id=290,
        class_id=321,
        setup_user_id=42,
        lti_status=canvas_connect_module.LTIStatus.LINKED,
        last_sync_error=None,
        last_synced=previous_sync,
    )

    async def _get_sync_context(self):
        return fake_lti_class, 321, 42

    async def _get_nrps_create_user_class_roles(self):
        return canvas_connect_module.CreateUserClassRoles(
            roles=[],
            silent=True,
            lms_type=canvas_connect_module.LMSType.CANVAS,
            lti_class_id=290,
        )

    class FakeAddNewUsersScript:
        def __init__(self, class_id, user_id, session, client, new_ucr):
            pass

        async def add_new_users(self):
            return canvas_connect_module.CreateUserResults(
                results=[
                    {"email": "ok@example.com", "display_name": "OK User"},
                    {
                        "email": "bad@example.com",
                        "display_name": "Broken User",
                        "error": "role update rejected",
                    },
                ]
            )

    monkeypatch.setattr(
        canvas_connect_module.CanvasConnectClient,
        "_get_sync_context",
        _get_sync_context,
    )
    monkeypatch.setattr(
        canvas_connect_module.CanvasConnectClient,
        "get_nrps_create_user_class_roles",
        _get_nrps_create_user_class_roles,
    )
    monkeypatch.setattr(
        canvas_connect_module,
        "AddNewUsersScript",
        FakeAddNewUsersScript,
    )

    db = FakeWriteDB()
    authz_client = SimpleNamespace()
    client = canvas_connect_module.ScriptCanvasConnectClient(
        db=db,
        client=authz_client,
        lti_class_id=290,
        key_manager=FakeKeyManager(),
        nowfn=lambda: fixed_now,
    )

    with pytest.raises(canvas_connect_module.CanvasConnectException) as excinfo:
        await client.sync_roster()

    assert "failed roster updates" in excinfo.value.detail
    assert "bad@example.com: role update rejected" in excinfo.value.detail
    assert fake_lti_class.lti_status == canvas_connect_module.LTIStatus.ERROR
    assert fake_lti_class.last_sync_error == excinfo.value.detail
    assert fake_lti_class.last_synced == previous_sync
    assert db.added == [fake_lti_class]
    assert db.flush_count == 1


@pytest.mark.asyncio
async def test_manual_canvas_connect_sync_roster_marks_error_on_row_failures(
    monkeypatch,
):
    fixed_now = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    previous_sync = fixed_now - timedelta(hours=3)
    fake_lti_class = SimpleNamespace(
        id=291,
        class_id=321,
        setup_user_id=42,
        lti_status=canvas_connect_module.LTIStatus.LINKED,
        last_sync_error=None,
        last_synced=previous_sync,
    )

    async def _get_sync_context(self):
        return fake_lti_class, 321, 42

    async def _get_nrps_create_user_class_roles(self):
        return canvas_connect_module.CreateUserClassRoles(
            roles=[],
            silent=True,
            lms_type=canvas_connect_module.LMSType.CANVAS,
            lti_class_id=291,
        )

    class FakeAddNewUsersManual:
        def __init__(self, class_id, new_ucr, request, tasks, user_id=None):
            pass

        async def add_new_users(self):
            return canvas_connect_module.CreateUserResults(
                results=[
                    {
                        "email": "broken@example.com",
                        "display_name": "Broken User",
                        "error": "role update rejected",
                    }
                ]
            )

    monkeypatch.setattr(
        canvas_connect_module.CanvasConnectClient,
        "_get_sync_context",
        _get_sync_context,
    )
    monkeypatch.setattr(
        canvas_connect_module.CanvasConnectClient,
        "get_nrps_create_user_class_roles",
        _get_nrps_create_user_class_roles,
    )
    monkeypatch.setattr(
        canvas_connect_module,
        "AddNewUsersManual",
        FakeAddNewUsersManual,
    )

    db = FakeWriteDB()
    request = SimpleNamespace(state={"db": db})
    tasks = SimpleNamespace()
    client = canvas_connect_module.ManualCanvasConnectClient(
        lti_class_id=291,
        request=request,
        tasks=tasks,
        key_manager=FakeKeyManager(),
        nowfn=lambda: fixed_now,
    )

    with pytest.raises(canvas_connect_module.CanvasConnectException) as excinfo:
        await client.sync_roster()

    assert "Syncing your roster through Canvas Connect failed" in excinfo.value.detail
    assert fake_lti_class.lti_status == canvas_connect_module.LTIStatus.ERROR
    assert (
        fake_lti_class.last_sync_error
        == "Canvas Connect sync had 1 failed roster updates: "
        "broken@example.com: role update rejected"
    )
    assert fake_lti_class.last_synced == previous_sync
    assert db.added == [fake_lti_class]
    assert db.flush_count == 1

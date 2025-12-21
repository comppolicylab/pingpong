import json
from datetime import datetime, timedelta, timezone

import pytest
from botocore.exceptions import ClientError

from pingpong.lti import key_manager as key_manager_module
from pingpong.lti.key_manager import (
    AWSLTIKeyStore,
    LTIKeyManager,
    LTIKeyPair,
    LTIKeyStoreError,
    LocalLTIKeyStore,
)


class InMemoryKeyStore(key_manager_module.BaseLTIKeyStore):
    def __init__(self, keys=None):
        self.keys = list(keys or [])
        self.saved = None

    async def load_keys(self):
        return list(self.keys)

    async def save_keys(self, keys):
        self.saved = list(keys)
        self.keys = list(keys)


class FakeSecretsClient:
    def __init__(
        self,
        secret_string=None,
        get_error=None,
        put_error=None,
        create_error=None,
    ):
        self.secret_string = secret_string
        self.get_error = get_error
        self.put_error = put_error
        self.create_error = create_error
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_secret_value(self, SecretId):
        self.calls.append(("get_secret_value", SecretId))
        if self.get_error:
            raise self.get_error
        return {"SecretString": self.secret_string}

    async def put_secret_value(self, SecretId, SecretString):
        self.calls.append(("put_secret_value", SecretId, SecretString))
        if self.put_error:
            raise self.put_error
        return {"ARN": "arn:aws:secretsmanager:region:acct:secret:test"}

    async def create_secret(self, Name, Description, SecretString):
        self.calls.append(("create_secret", Name, Description, SecretString))
        if self.create_error:
            raise self.create_error
        return {"ARN": "arn:aws:secretsmanager:region:acct:secret:test"}


class FakeSession:
    def __init__(self, client):
        self._client = client

    def client(self, service_name):
        assert service_name == "secretsmanager"
        return self._client


def _client_error(code, operation="operation"):
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, operation)


def _make_key_pair(kid, created_at):
    return LTIKeyPair(
        kid=kid,
        private_key_pem="priv",
        public_key_pem="pub",
        created_at=created_at,
    )


def test_lti_key_store_error_fields():
    err = LTIKeyStoreError(detail="boom", code=500)
    assert err.detail == "boom"
    assert err.code == 500


def test_lti_key_pair_to_dict_round_trip():
    now = datetime.now(timezone.utc)
    pair = LTIKeyPair(
        kid="kid",
        private_key_pem="priv",
        public_key_pem="pub",
        created_at=now,
    )

    data = pair.to_dict()
    assert data["created_at"] == now.isoformat()

    rebuilt = LTIKeyPair.from_dict(data)
    assert rebuilt.kid == pair.kid
    assert rebuilt.private_key_pem == pair.private_key_pem
    assert rebuilt.public_key_pem == pair.public_key_pem
    assert rebuilt.created_at == now


def test_lti_key_pair_to_jwk_contains_key_material():
    manager = LTIKeyManager(InMemoryKeyStore())
    pair = manager._generate_key_pair()
    jwk = pair.to_jwk()

    assert jwk["kty"] == "RSA"
    assert jwk["kid"] == pair.kid
    assert jwk["use"] == pair.use
    assert jwk["alg"] == pair.algorithm
    assert jwk["n"]
    assert jwk["e"]
    assert "=" not in jwk["n"]
    assert "=" not in jwk["e"]


@pytest.mark.asyncio
async def test_aws_key_store_load_keys_sorted(monkeypatch):
    now = datetime.now(timezone.utc)
    older = _make_key_pair("old", now - timedelta(days=1))
    newer = _make_key_pair("new", now)
    secret_string = json.dumps({"keys": [older.to_dict(), newer.to_dict()]})
    client = FakeSecretsClient(secret_string=secret_string)

    monkeypatch.setattr(
        key_manager_module.aioboto3, "Session", lambda: FakeSession(client)
    )

    store = AWSLTIKeyStore("secret")
    keys = await store.load_keys()

    assert [key.kid for key in keys] == ["new", "old"]


@pytest.mark.asyncio
async def test_aws_key_store_load_missing_secret(monkeypatch):
    client = FakeSecretsClient(get_error=_client_error("ResourceNotFoundException"))
    monkeypatch.setattr(
        key_manager_module.aioboto3, "Session", lambda: FakeSession(client)
    )

    store = AWSLTIKeyStore("secret")
    keys = await store.load_keys()

    assert keys == []


@pytest.mark.asyncio
async def test_aws_key_store_load_error(monkeypatch):
    client = FakeSecretsClient(get_error=_client_error("AccessDeniedException"))
    monkeypatch.setattr(
        key_manager_module.aioboto3, "Session", lambda: FakeSession(client)
    )

    store = AWSLTIKeyStore("secret")
    with pytest.raises(LTIKeyStoreError) as excinfo:
        await store.load_keys()

    assert excinfo.value.code == 500


@pytest.mark.asyncio
async def test_aws_key_store_save_keys_puts_secret(monkeypatch):
    client = FakeSecretsClient()
    monkeypatch.setattr(
        key_manager_module.aioboto3, "Session", lambda: FakeSession(client)
    )

    store = AWSLTIKeyStore("secret")
    await store.save_keys([_make_key_pair("kid", datetime.now(timezone.utc))])

    assert any(call[0] == "put_secret_value" for call in client.calls)
    assert not any(call[0] == "create_secret" for call in client.calls)


@pytest.mark.asyncio
async def test_aws_key_store_save_keys_creates_missing_secret(monkeypatch):
    client = FakeSecretsClient(put_error=_client_error("ResourceNotFoundException"))
    monkeypatch.setattr(
        key_manager_module.aioboto3, "Session", lambda: FakeSession(client)
    )

    store = AWSLTIKeyStore("secret")
    await store.save_keys([_make_key_pair("kid", datetime.now(timezone.utc))])

    assert any(call[0] == "create_secret" for call in client.calls)


@pytest.mark.asyncio
async def test_aws_key_store_save_keys_error(monkeypatch):
    client = FakeSecretsClient(put_error=_client_error("AccessDeniedException"))
    monkeypatch.setattr(
        key_manager_module.aioboto3, "Session", lambda: FakeSession(client)
    )

    store = AWSLTIKeyStore("secret")
    with pytest.raises(LTIKeyStoreError) as excinfo:
        await store.save_keys([_make_key_pair("kid", datetime.now(timezone.utc))])

    assert excinfo.value.code == 500


@pytest.mark.asyncio
async def test_local_key_store_missing_file(tmp_path):
    store = LocalLTIKeyStore(str(tmp_path))
    keys = await store.load_keys()

    assert keys == []


@pytest.mark.asyncio
async def test_local_key_store_save_and_load(tmp_path):
    store = LocalLTIKeyStore(str(tmp_path))
    now = datetime.now(timezone.utc)
    older = _make_key_pair("old", now - timedelta(days=1))
    newer = _make_key_pair("new", now)

    await store.save_keys([older, newer])
    keys = await store.load_keys()

    assert [key.kid for key in keys] == ["new", "old"]


@pytest.mark.asyncio
async def test_local_key_store_load_invalid_json(tmp_path):
    store = LocalLTIKeyStore(str(tmp_path))
    with open(tmp_path / "keys.json", "w") as f:
        f.write("not json")

    with pytest.raises(LTIKeyStoreError) as excinfo:
        await store.load_keys()

    assert excinfo.value.code == 500


@pytest.mark.asyncio
async def test_local_key_store_save_error(tmp_path, monkeypatch):
    store = LocalLTIKeyStore(str(tmp_path))

    def _raise_open(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr("builtins.open", _raise_open)

    with pytest.raises(LTIKeyStoreError) as excinfo:
        await store.save_keys([_make_key_pair("kid", datetime.now(timezone.utc))])

    assert excinfo.value.code == 500


def test_generate_key_pair():
    manager = LTIKeyManager(InMemoryKeyStore())
    pair = manager._generate_key_pair()

    assert pair.kid
    assert "_" in pair.kid
    assert pair.private_key_pem.startswith("-----BEGIN PRIVATE KEY-----")
    assert pair.public_key_pem.startswith("-----BEGIN PUBLIC KEY-----")
    assert pair.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_rotate_keys_retention(monkeypatch):
    now = datetime.now(timezone.utc)
    existing = [
        _make_key_pair("a", now - timedelta(days=2)),
        _make_key_pair("b", now - timedelta(days=1)),
        _make_key_pair("c", now - timedelta(hours=1)),
    ]
    store = InMemoryKeyStore(keys=existing)
    manager = LTIKeyManager(store)
    new_key = _make_key_pair("new", now)

    monkeypatch.setattr(manager, "_generate_key_pair", lambda key_size=2048: new_key)

    rotated = await manager.rotate_keys(retention_count=2)

    assert rotated.kid == "new"
    assert [key.kid for key in store.saved] == ["new", "a"]


@pytest.mark.asyncio
async def test_get_current_key_empty():
    manager = LTIKeyManager(InMemoryKeyStore())
    assert await manager.get_current_key() is None


@pytest.mark.asyncio
async def test_get_current_key_returns_first():
    now = datetime.now(timezone.utc)
    store = InMemoryKeyStore(keys=[_make_key_pair("kid", now)])
    manager = LTIKeyManager(store)

    key = await manager.get_current_key()
    assert key.kid == "kid"


@pytest.mark.asyncio
async def test_get_key_by_kid_found_and_missing():
    now = datetime.now(timezone.utc)
    store = InMemoryKeyStore(keys=[_make_key_pair("kid", now)])
    manager = LTIKeyManager(store)

    assert (await manager.get_key_by_kid("kid")).kid == "kid"
    assert await manager.get_key_by_kid("missing") is None


@pytest.mark.asyncio
async def test_get_public_keys_jwks():
    manager = LTIKeyManager(InMemoryKeyStore())
    pair = manager._generate_key_pair()
    store = InMemoryKeyStore(keys=[pair])
    manager = LTIKeyManager(store)

    jwks = await manager.get_public_keys_jwks()

    assert jwks["keys"][0]["kid"] == pair.kid


@pytest.mark.asyncio
async def test_sign_and_verify_jwt_round_trip():
    manager = LTIKeyManager(InMemoryKeyStore())
    pair = manager._generate_key_pair()
    store = InMemoryKeyStore(keys=[pair])
    manager = LTIKeyManager(store)
    payload = {"sub": "user", "role": "instructor"}

    token = await manager.sign_jwt(payload)
    decoded = await manager.verify_jwt(token, pair.kid)

    assert decoded["sub"] == "user"
    assert decoded["role"] == "instructor"


@pytest.mark.asyncio
async def test_sign_jwt_missing_key_id():
    manager = LTIKeyManager(InMemoryKeyStore())

    with pytest.raises(ValueError):
        await manager.sign_jwt({"sub": "user"})


@pytest.mark.asyncio
async def test_sign_jwt_kid_not_found():
    manager = LTIKeyManager(InMemoryKeyStore())

    with pytest.raises(ValueError):
        await manager.sign_jwt({"sub": "user"}, kid="missing")


@pytest.mark.asyncio
async def test_verify_jwt_kid_not_found():
    manager = LTIKeyManager(InMemoryKeyStore())

    with pytest.raises(ValueError):
        await manager.verify_jwt("token", kid="missing")

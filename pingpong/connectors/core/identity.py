from __future__ import annotations

from abc import abstractmethod
import asyncio
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from authlib.integrations.httpx_client import AsyncOAuth2Client
import httpx
import jwt
from jwt import PyJWK, PyJWKSet

from .exceptions import ConnectorError
from .types import ConnectorTokens, ProviderIdentity

if TYPE_CHECKING:
    from pingpong.models import ConnectorConfig


class IdentityConnector(Protocol):
    http_timeout_seconds: ClassVar[float]

    @abstractmethod
    async def userinfo_endpoint(
        self, connector_config: "ConnectorConfig"
    ) -> str | None:
        raise NotImplementedError

    @abstractmethod
    async def issuer(self, connector_config: "ConnectorConfig") -> str | None:
        raise NotImplementedError

    @abstractmethod
    async def jwks_endpoint(self, connector_config: "ConnectorConfig") -> str | None:
        raise NotImplementedError

    @abstractmethod
    def oauth_client(
        self,
        connector_config: "ConnectorConfig",
        *,
        token: dict[str, Any] | None = None,
    ) -> AsyncOAuth2Client:
        raise NotImplementedError

    @abstractmethod
    def token_dict(self, tokens: ConnectorTokens) -> dict[str, Any]:
        raise NotImplementedError


class ConnectorIdentityResolver:
    def __init__(self) -> None:
        self._jwks_cache: dict[str, PyJWKSet] = {}
        self._jwks_lock = asyncio.Lock()

    async def fetch_identity(
        self,
        connector: IdentityConnector,
        *,
        connector_config: "ConnectorConfig",
        tokens: ConnectorTokens,
        expected_nonce: str | None = None,
    ) -> ProviderIdentity:
        endpoint = await connector.userinfo_endpoint(connector_config)
        if endpoint is None:
            return await self.identity_from_id_token(
                connector,
                connector_config=connector_config,
                tokens=tokens,
                expected_nonce=expected_nonce,
            )
        async with connector.oauth_client(
            connector_config, token=connector.token_dict(tokens)
        ) as client:
            try:
                response = await client.get(endpoint)
            except httpx.HTTPError as e:
                raise ConnectorError(f"Userinfo request failed: {e}") from e
        if response.status_code >= 400:
            raise ConnectorError(
                f"Userinfo endpoint returned {response.status_code}: "
                f"{response.text[:200]}"
            )
        try:
            payload = response.json()
        except ValueError as e:
            raise ConnectorError("Userinfo endpoint returned non-JSON response") from e
        if not isinstance(payload, dict):
            raise ConnectorError("Userinfo endpoint returned non-object payload")
        return self.identity_from_userinfo(payload)

    async def identity_from_id_token(
        self,
        connector: IdentityConnector,
        *,
        connector_config: "ConnectorConfig",
        tokens: ConnectorTokens,
        expected_nonce: str | None = None,
    ) -> ProviderIdentity:
        raw = tokens.raw or {}
        id_token = raw.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            return ProviderIdentity(external_user_id=None, external_identity=None)

        issuer = await connector.issuer(connector_config)
        jwks_uri = await connector.jwks_endpoint(connector_config)
        if issuer is None or jwks_uri is None:
            raise ConnectorError(
                "ID token fallback requires issuer and jwks_uri discovery fields"
            )

        try:
            header = jwt.get_unverified_header(id_token)
            key = await self._jwk_for_token(
                jwks_uri, header, timeout=connector.http_timeout_seconds
            )
            payload = jwt.decode(
                id_token,
                key=key.key,
                algorithms=[key.algorithm_name],
                audience=connector_config.client_id,
                issuer=issuer,
                options={"require": ["sub", "iss", "aud", "exp"]},
            )
        except jwt.PyJWTError as e:
            raise ConnectorError(f"ID token validation failed: {e}") from e

        if expected_nonce is not None and payload.get("nonce") != expected_nonce:
            raise ConnectorError("ID token nonce mismatch")

        sub = payload.get("sub")
        if not isinstance(sub, str) or not sub:
            raise ConnectorError("ID token missing sub")
        return ProviderIdentity(
            external_user_id=sub,
            external_identity={
                "source": "id_token",
                "claims": self._sanitize_external_identity(payload),
            },
        )

    def identity_from_userinfo(self, payload: dict[str, Any]) -> ProviderIdentity:
        sub = payload.get("sub")
        if not isinstance(sub, str) or not sub:
            raise ConnectorError("Userinfo response missing sub")
        return ProviderIdentity(
            external_user_id=sub,
            external_identity={
                "source": "userinfo",
                "claims": self._sanitize_external_identity(payload),
            },
        )

    async def _jwk_for_token(
        self, jwks_uri: str, header: dict[str, Any], *, timeout: float
    ) -> PyJWK:
        alg = header.get("alg")
        if not isinstance(alg, str) or alg.lower() == "none":
            raise ConnectorError("ID token missing supported signing algorithm")
        kid = header.get("kid")
        key_set = await self._load_jwks(jwks_uri, timeout=timeout)
        if isinstance(kid, str):
            key = self._matching_key(key_set, kid=kid, alg=alg)
            if key is not None:
                return key

            key_set = await self._load_jwks(
                jwks_uri, timeout=timeout, force_refresh=True
            )
            key = self._matching_key(key_set, kid=kid, alg=alg)
            if key is not None:
                return key
            raise ConnectorError("ID token signing key not found in JWKS")
        if len(key_set.keys) == 1 and key_set.keys[0].algorithm_name == alg:
            return key_set.keys[0]
        raise ConnectorError("ID token missing kid")

    def _matching_key(self, key_set: PyJWKSet, *, kid: str, alg: str) -> PyJWK | None:
        for key in key_set.keys:
            if key.key_id == kid:
                if key.algorithm_name != alg:
                    raise ConnectorError("ID token key algorithm mismatch")
                return key
        return None

    async def _load_jwks(
        self, jwks_uri: str, *, timeout: float, force_refresh: bool = False
    ) -> PyJWKSet:
        if not force_refresh and jwks_uri in self._jwks_cache:
            return self._jwks_cache[jwks_uri]
        async with self._jwks_lock:
            if not force_refresh and jwks_uri in self._jwks_cache:
                return self._jwks_cache[jwks_uri]
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(jwks_uri)
            except httpx.HTTPError as e:
                raise ConnectorError(f"JWKS request failed: {e}") from e
            if response.status_code >= 400:
                raise ConnectorError(
                    f"JWKS endpoint returned {response.status_code}: "
                    f"{response.text[:200]}"
                )
            try:
                payload = response.json()
            except ValueError as e:
                raise ConnectorError("JWKS endpoint returned non-JSON response") from e
            if not isinstance(payload, dict):
                raise ConnectorError("JWKS endpoint returned non-object payload")
            try:
                key_set = PyJWKSet.from_dict(payload)
            except jwt.PyJWTError as e:
                raise ConnectorError(f"JWKS endpoint returned invalid keys: {e}") from e
            self._jwks_cache[jwks_uri] = key_set
            return key_set

    def _sanitize_external_identity(self, value: Any) -> Any:
        if isinstance(value, dict):
            clean: dict[str, Any] = {}
            for key, item in value.items():
                key_str = str(key)
                lowered = key_str.lower()
                if any(
                    blocked in lowered
                    for blocked in (
                        "token",
                        "secret",
                        "authorization",
                        "cookie",
                        "header",
                    )
                ):
                    continue
                clean[key_str] = self._sanitize_external_identity(item)
            return clean
        if isinstance(value, list):
            return [self._sanitize_external_identity(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

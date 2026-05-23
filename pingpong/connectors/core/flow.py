from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.now import NowFn, utcnow

from .base import OAuth2Connector, generate_pkce_pair
from .exceptions import ConnectorFlowError
from .models import load_connector_config_by_id, upsert_user_connector
from .registry import get
from .state import decode_state, encode_state, generate_nonce
from .types import CallbackResult, ConnectIntent

if TYPE_CHECKING:
    from pingpong.models import ConnectorConfig


async def begin_connect(
    session: AsyncSession,
    *,
    user_id: int,
    service: str,
    connector_config_id: int,
    redirect_uri: str,
    nowfn: NowFn = utcnow,
) -> ConnectIntent:
    connector = get(service)
    connector_config = await _load_available_connector_config(
        session,
        connector=connector,
        connector_config_id=connector_config_id,
    )
    pkce = generate_pkce_pair() if connector.use_pkce else None
    nonce = generate_nonce()
    state = encode_state(
        user_id=user_id,
        service=service,
        connector_config_id=connector_config.id,
        pkce_verifier=pkce.verifier if pkce else None,
        nonce=nonce,
        nowfn=nowfn,
    )
    url = await connector.build_authorize_url(
        connector_config=connector_config,
        redirect_uri=redirect_uri,
        state=state,
        pkce=pkce,
        nonce=nonce,
    )
    return ConnectIntent(
        url=url,
        state=state,
        nonce=nonce,
        pkce=pkce,
        connector_config=connector_config,
    )


async def complete_callback(
    session: AsyncSession,
    *,
    service: str,
    code: str,
    state: str,
    session_user_id: int,
    redirect_uri: str,
    nowfn: NowFn = utcnow,
) -> CallbackResult:
    decoded = decode_state(state, nowfn=nowfn)
    if decoded.get("service") != service:
        raise ConnectorFlowError("service_mismatch")

    try:
        state_user_id = int(decoded["sub"])
    except (KeyError, TypeError, ValueError) as e:
        raise ConnectorFlowError(
            "bad_state", "OAuth state token has invalid sub"
        ) from e
    if state_user_id != session_user_id:
        raise ConnectorFlowError("user_mismatch")

    connector = get(service)
    connector_config_id = decoded.get("connector_config_id")
    if not isinstance(connector_config_id, int):
        raise ConnectorFlowError(
            "bad_state", "OAuth state token has invalid connector_config_id"
        )
    connector_config = await _load_available_connector_config(
        session,
        connector=connector,
        connector_config_id=connector_config_id,
    )

    pkce_verifier = decoded.get("pkce_verifier")
    if pkce_verifier is not None and not isinstance(pkce_verifier, str):
        raise ConnectorFlowError("bad_state", "OAuth state token has invalid PKCE")
    if connector.use_pkce and not pkce_verifier:
        raise ConnectorFlowError(
            "bad_state", "OAuth state token is missing PKCE verifier"
        )
    nonce = decoded.get("nonce")
    if nonce is not None and not isinstance(nonce, str):
        raise ConnectorFlowError("bad_state", "OAuth state token has invalid nonce")

    tokens = await connector.exchange_code(
        connector_config=connector_config,
        code=code,
        redirect_uri=redirect_uri,
        state=state,
        pkce_verifier=pkce_verifier,
    )
    identity = await connector.fetch_identity(
        connector_config=connector_config,
        tokens=tokens,
        expected_nonce=nonce,
    )
    row = await upsert_user_connector(
        session,
        user_id=state_user_id,
        connector_config=connector_config,
        tokens=tokens,
        identity=identity,
    )
    return CallbackResult(
        row=row,
        connector_config=connector_config,
        tokens=tokens,
        identity=identity,
    )


async def _load_available_connector_config(
    session: AsyncSession,
    *,
    connector: OAuth2Connector,
    connector_config_id: int,
) -> "ConnectorConfig":
    connector_config = await load_connector_config_by_id(session, connector_config_id)
    if connector_config.service != connector.slug:
        raise ConnectorFlowError("connector_config_mismatch")
    if not connector_config.enabled:
        raise ConnectorFlowError("connector_config_disabled")
    return connector_config

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, TypedDict

from yarl import URL

import aiohttp

from pingpong.lti.constants import MAX_LTI_REDIRECTS


class RedirectValidationRequestContext(TypedDict):
    validate_redirect_url: Callable[[str], str]
    redirects_allowed: bool


async def _validate_redirect(
    _session: aiohttp.ClientSession,
    trace_config_ctx: object,
    params: Any,
) -> None:
    trace_request_ctx = getattr(trace_config_ctx, "trace_request_ctx", None)
    if not isinstance(trace_request_ctx, dict):
        return

    validate_redirect_url = trace_request_ctx.get("validate_redirect_url")
    redirects_allowed = trace_request_ctx.get("redirects_allowed")
    if not callable(validate_redirect_url) or not isinstance(redirects_allowed, bool):
        return

    if not redirects_allowed:
        raise ValueError("Redirects are not allowed")

    response = params.response
    location = response.headers.get("Location") or response.headers.get("URI")
    if not location:
        raise ValueError("Redirect response is missing a Location header")

    validate_redirect_url(str(params.url.join(URL(location))))


def create_lti_redirect_trace_config() -> aiohttp.TraceConfig:
    trace_config = aiohttp.TraceConfig()
    trace_config.on_request_redirect.append(_validate_redirect)
    trace_config.freeze()
    return trace_config


@asynccontextmanager
async def request_with_validated_redirects(
    *,
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    validate_redirect_url: Callable[[str], str],
    redirects_allowed: bool,
    **request_kwargs: Any,
) -> AsyncIterator[aiohttp.ClientResponse]:
    trace_request_ctx: RedirectValidationRequestContext = {
        "validate_redirect_url": validate_redirect_url,
        "redirects_allowed": redirects_allowed,
    }
    async with session.request(
        method,
        url,
        allow_redirects=True,
        max_redirects=MAX_LTI_REDIRECTS + 1,
        trace_request_ctx=trace_request_ctx,
        **request_kwargs,
    ) as response:
        yield response

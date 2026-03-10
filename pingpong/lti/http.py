from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import AsyncContextManager
from urllib.parse import urljoin

import aiohttp

from pingpong.lti.constants import MAX_LTI_REDIRECTS

REDIRECT_STATUSES = {301, 302, 303, 307, 308}


@asynccontextmanager
async def request_with_validated_redirects(
    *,
    initial_url: str,
    request: Callable[[str], AsyncContextManager[aiohttp.ClientResponse]],
    validate_redirect_url: Callable[[str], str],
    redirects_allowed: bool,
    unexpected_redirect_error: Callable[[], Exception],
    invalid_redirect_response_error: Callable[[], Exception],
    too_many_redirects_error: Callable[[], Exception],
    invalid_redirect_url_error: Callable[[ValueError], Exception],
) -> AsyncIterator[tuple[aiohttp.ClientResponse, str]]:
    current_url = initial_url
    redirect_count = 0

    while True:
        async with request(current_url) as response:
            if response.status in REDIRECT_STATUSES:
                if not redirects_allowed:
                    raise unexpected_redirect_error()

                location = response.headers.get("Location")
                if not location:
                    raise invalid_redirect_response_error()

                redirect_count += 1
                if redirect_count > MAX_LTI_REDIRECTS:
                    raise too_many_redirects_error()

                try:
                    current_url = validate_redirect_url(urljoin(current_url, location))
                except ValueError as e:
                    raise invalid_redirect_url_error(e) from e
                continue

            yield response, current_url
            return

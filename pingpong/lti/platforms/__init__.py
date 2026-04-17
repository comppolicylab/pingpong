"""Per-platform LTI handler registry.

Use `get_handler(platform)` to obtain a handler that encapsulates the
platform-specific parts of the LTI registration and launch flows.
"""

from pingpong.lti.platforms.base import (
    LTIPlatformHandler,
    parse_context_memberships_url,
)
from pingpong.lti.platforms.canvas import CanvasPlatformHandler
from pingpong.lti.platforms.harvard_lxp import HarvardLxpPlatformHandler
from pingpong.schemas import LMSPlatform


_HANDLERS: dict[LMSPlatform, type[LTIPlatformHandler]] = {
    LMSPlatform.CANVAS: CanvasPlatformHandler,
    LMSPlatform.HARVARD_LXP: HarvardLxpPlatformHandler,
}


def get_handler(platform: LMSPlatform) -> LTIPlatformHandler:
    try:
        handler_cls = _HANDLERS[platform]
    except KeyError as e:
        raise ValueError(f"No LTI handler registered for platform {platform}") from e
    return handler_cls()


__all__ = [
    "LTIPlatformHandler",
    "CanvasPlatformHandler",
    "HarvardLxpPlatformHandler",
    "get_handler",
    "parse_context_memberships_url",
]

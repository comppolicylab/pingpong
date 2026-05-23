"""Public facade for registered OAuth connectors."""

from __future__ import annotations

from .core.flow import CallbackResult, ConnectIntent, begin_connect, complete_callback
from .core.registry import register
from .panopto import PanoptoConnector as _PanoptoConnector

register(_PanoptoConnector())

__all__ = [
    "begin_connect",
    "CallbackResult",
    "complete_callback",
    "ConnectIntent",
]

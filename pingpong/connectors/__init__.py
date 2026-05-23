"""Public facade for registered OAuth connectors."""

from __future__ import annotations

from .core.flow import begin_connect, complete_callback
from .core.exceptions import ConnectorValidationError
from .core.types import CallbackResult, ConnectIntent
from .core.registry import register, all_connectors, get as get_connector
from .panopto import PanoptoConnector as _PanoptoConnector

register(_PanoptoConnector())

__all__ = [
    "all_connectors",
    "begin_connect",
    "CallbackResult",
    "complete_callback",
    "ConnectIntent",
    "ConnectorValidationError",
    "get_connector",
]

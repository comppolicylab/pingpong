class ConnectorError(Exception):
    """Base error raised by the connector framework."""


class ConnectorNotConfigured(ConnectorError):
    """Raised when a connector or connector config cannot be used."""


class ConnectorNotRegistered(ConnectorError):
    """Raised when looking up an unknown connector slug."""


class ConnectorFlowError(ConnectorError):
    """Raised when the OAuth connect/callback flow cannot continue."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class TokenRefreshError(ConnectorError):
    """Raised when refreshing an OAuth2 access token fails."""


class OAuthStateError(ConnectorError):
    """Raised when the OAuth2 state JWT fails to validate."""

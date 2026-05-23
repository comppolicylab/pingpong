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


class ConnectorValidationError(ConnectorError):
    """Raised when an admin-submitted connector configuration fails validation.

    ``field`` names the part of the config that failed ("host" or "credentials")
    so the API layer can surface a structured error to the UI.
    """

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")

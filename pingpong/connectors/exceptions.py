class ConnectorError(Exception):
    """Base error raised by the connector framework."""


class ConnectorNotConfigured(ConnectorError):
    """Raised when a connector or tenant has no configuration entry."""


class ConnectorNotRegistered(ConnectorError):
    """Raised when looking up an unknown connector slug."""


class TokenRefreshError(ConnectorError):
    """Raised when refreshing an OAuth2 access token fails."""


class OAuthStateError(ConnectorError):
    """Raised when the OAuth2 state JWT fails to validate."""

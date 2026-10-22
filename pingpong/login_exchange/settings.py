"""Configuration for the optional SAML login exchange."""

from urllib.parse import urlsplit

from pydantic import Field, field_validator

from ..redis.settings import RedisSettings


class LoginExchangeSettings(RedisSettings):
    """Optional Redis-backed exchange between trusted login origins."""

    target_origin: str
    source_origins: list[str]
    ttl_seconds: int = Field(60, ge=1, le=300)

    @field_validator("target_origin")
    @classmethod
    def validate_target_origin(cls, value: str) -> str:
        cls.validate_origin(value, "target_origin")
        return value

    @field_validator("source_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            cls.validate_origin(value, "source_origins")
        return values

    @staticmethod
    def validate_origin(value: str, field: str) -> None:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or any(c.isspace() or c == "\\" for c in value)
        ):
            raise ValueError(
                f"{field} must contain exact HTTP(S) origins without paths"
            )
        _ = parsed.port

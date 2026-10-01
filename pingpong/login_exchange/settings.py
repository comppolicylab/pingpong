"""Configuration for the optional SAML login exchange."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings


class LoginExchangeSettings(BaseSettings):
    """Optional Redis-backed exchange between trusted login origins."""

    redis_url: SecretStr
    cache_name: str | None = Field(None, min_length=1)
    elasticache_user: str | None = Field(None, min_length=1)
    region: str | None = Field(None, min_length=1)
    cache_type: Literal["serverless", "replication_group"] = "serverless"
    target_origin: str
    source_origins: list[str]
    ttl_seconds: int = Field(60, ge=1, le=300)
    max_connections: int = Field(10, ge=1, le=100)

    @field_validator("cache_name")
    @classmethod
    def normalize_cache_name(cls, value: str | None) -> str | None:
        return value.lower() if value is not None else None

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        parsed = urlsplit(value.get_secret_value())
        if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
            raise ValueError("redis_url must be a redis:// or rediss:// URL")
        # URL options override the client's safety settings.
        if parsed.query or parsed.fragment:
            raise ValueError("redis_url must not contain query options or a fragment")
        _ = parsed.port
        return value

    @model_validator(mode="after")
    def validate_connection_mode(self):
        iam_values = (self.cache_name, self.elasticache_user, self.region)
        if any(iam_values) and not all(iam_values):
            raise ValueError(
                "Set cache_name, elasticache_user, and region together for IAM auth"
            )
        if (
            all(iam_values)
            and urlsplit(self.redis_url.get_secret_value()).scheme != "rediss"
        ):
            raise ValueError("ElastiCache IAM authentication requires a rediss:// URL")
        return self

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

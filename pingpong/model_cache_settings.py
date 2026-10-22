"""Configuration for the optional shared provider model catalog cache."""

from pydantic import Field
from pydantic_settings import BaseSettings

from .redis.settings import RedisSettings


class ModelCacheSettings(BaseSettings):
    redis: RedisSettings | None = None
    ttl_seconds: int = Field(86400, ge=60, le=604800)
    # Use the same immutable build identifier on every worker in a deployment.
    build_revision: str | None = None

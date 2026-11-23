from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..login_exchange.settings import LoginExchangeSettings
from ..redis.settings import RedisSettings


class OpenAccessSettings(RedisSettings):
    client_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    public_key: str = Field(min_length=1)
    signing_algorithm: Literal["ES256", "EdDSA"] = "ES256"
    origin: str
    assistant_ids: list[int] = Field(min_length=1)
    free_assistant_id: int
    paused: bool = False
    anonymous_paused: bool = False
    grant_max_age_seconds: int = Field(60, ge=1, le=300)
    launch_code_ttl_seconds: int = Field(60, ge=1, le=300)
    access_token_ttl_seconds: int = Field(600, ge=60, le=3600)

    @field_validator("origin")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        LoginExchangeSettings.validate_origin(value, "origin")
        return value

    @model_validator(mode="after")
    def validate_free_assistant(self):
        if self.free_assistant_id not in self.assistant_ids:
            raise ValueError("free_assistant_id must be one of assistant_ids")
        return self

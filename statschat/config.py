import os
import tomllib
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class SlackSettings(BaseSettings):
    """Slack settings."""

    app_id: str
    client_id: str
    client_secret: str
    signing_secret: str


class OpenAIApiSettings(BaseSettings):
    """OpenAI API settings."""

    type: str
    base: str
    chat_version: str
    key: str


class AzureOpenAISettings(BaseSettings):
    """Azure OpenAI settings."""

    engine: str
    temperature: float = Field(0.2)
    top_p: float = Field(0.95)

    api: OpenAIApiSettings


class AzureSettings(BaseSettings):
    """Azure settings."""

    oai: AzureOpenAISettings


class Config(BaseSettings):
    """Stats Chat Bot config."""
    
    log_level: str = Field("INFO", env="LOG_LEVEL")

    slack: SlackSettings
    azure: AzureSettings


_config_path = os.environ.get('CONFIG_PATH', "config.toml")

config = Config.parse_obj(tomllib.loads(Path(_config_path).read_text()))

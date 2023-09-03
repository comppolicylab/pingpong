import os
import tomllib
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class TutorSettings(BaseSettings):
    """Tutor settings."""

    prompt_file: str = Field(os.path.join("statschat", "prompts", "stats-tutor.txt"))
    loading_reaction: str = Field("thinking_face")


class SlackSettings(BaseSettings):
    """Slack settings."""

    app_id: str
    client_id: str
    client_secret: str
    signing_secret: str
    web_token: str
    socket_token: str


class OpenAIApiSettings(BaseSettings):
    """OpenAI API settings."""

    type: str = Field("azure")
    base: str
    chat_version: str
    key: str


class AzureOpenAISettings(BaseSettings):
    """Azure OpenAI settings."""

    engine: str
    temperature: float = Field(0.2)
    top_p: float = Field(0.95)

    api: OpenAIApiSettings


class AzureCSSettings(BaseSettings):
    """Azure cognitive search settings."""

    key: str
    endpoint: str
    index_name: str
    restrict_answers_to_data: bool = Field(True)
    type: str = Field("AzureCognitiveSearch")


class AzureSettings(BaseSettings):
    """Azure settings."""

    oai: AzureOpenAISettings
    cs: AzureCSSettings


class Config(BaseSettings):
    """Stats Chat Bot config."""
    
    log_level: str = Field("INFO", env="LOG_LEVEL")

    slack: SlackSettings
    azure: AzureSettings
    tutor: TutorSettings


_config_path = os.environ.get('CONFIG_PATH', "config.toml")

config = Config.parse_obj(tomllib.loads(Path(_config_path).read_text()))

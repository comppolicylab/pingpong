import os
import tomllib
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

from .text import GREETING, DEFAULT_SYSTEM_PROMPT


class Example(BaseSettings):
    """Example chat turn for few-shot tuning."""

    user: str
    ai: str


class Prompt(BaseSettings):
    """Describe a prompt."""

    system: str = Field(DEFAULT_SYSTEM_PROMPT)
    examples: list[Example] = Field([])
    focus: str


class Channel(BaseSettings):
    """Describe one slack channel integration."""

    team_id: str
    channel_id: str
    loading_reaction: str = Field("")
    cs_index_name: str = Field("")
    prompt: Prompt | dict | None = Field(None)


class TutorSettings(BaseSettings):
    """Tutor settings."""

    default_prompt: Prompt
    channels: list[Channel]
    db_dir: str = Field(".db")
    loading_reaction: str = Field("thinking_face")
    cs_index_name: str
    greeting: str = Field(GREETING)


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
    restrict_answers_to_data: bool = Field(True)
    type: str = Field("AzureCognitiveSearch")


class AzureSettings(BaseSettings):
    """Azure settings."""

    oai: AzureOpenAISettings
    cs: AzureCSSettings


class SentrySettings(BaseSettings):
    """Sentry settings."""

    dsn: str


class Config(BaseSettings):
    """Stats Chat Bot config."""
    
    log_level: str = Field("INFO", env="LOG_LEVEL")

    azure: AzureSettings
    sentry: SentrySettings
    slack: SlackSettings
    tutor: TutorSettings

    def get_channel(self, team_id: str, channel_id: str) -> Channel:
        """Get the config for a channel.

        Args:
            team_id: Team (workspace) ID
            channel_id: Channel ID

        Returns:
            Config for the channel
        """
        for channel in self.tutor.channels:
            if channel.channel_id == channel_id and channel.team_id == team_id:
                return channel

        return Channel(
                team_id="",
                channel_id="",
                loading_reaction=self.tutor.loading_reaction,
                cs_index_name=self.tutor.cs_index_name,
                prompt=self.tutor.default_prompt,
                )


def load_config(path: str = os.environ.get('CONFIG_PATH', "config.toml")):
    """Parse config file from path.

    Args:
        path (str, optional): Path to config file. Defaults to "config.toml".

    Returns:
        Config: Parsed config object.
    """
    parsed = Config.parse_obj(tomllib.loads(Path(path).read_text()))

    # TODO - can just merge this with the channel config stuff above

    # Set defaults for channel-specific prompts.
    for channel in parsed.tutor.channels:
        prompt = parsed.tutor.default_prompt.dict()
        overrides = channel.prompt.dict() if isinstance(channel.prompt, Prompt) else (channel.prompt or {})
        prompt.update(overrides)
        channel.prompt = Prompt.parse_obj(prompt)

        # Set other defaults
        channel.loading_reaction = channel.loading_reaction or parsed.tutor.loading_reaction
        channel.cs_index_name = channel.cs_index_name or parsed.tutor.cs_index_name

    return parsed


# Globally available config object.
config = load_config()

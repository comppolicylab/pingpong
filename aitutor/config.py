import os
import tomllib
from pathlib import Path
from typing import Union

from pydantic import Field, model_validator
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
    prompt: Prompt | dict | None = Field(None)
    models: list[str]


class TutorSettings(BaseSettings):
    """Tutor settings."""

    default_prompt: Prompt
    channels: list[Channel]
    db_dir: str = Field(".db")
    switch_model: str = Field("switch")
    loading_reaction: str = Field("thinking_face")
    greeting: str = Field(GREETING)


class SlackSettings(BaseSettings):
    """Slack settings."""

    app_id: str
    client_id: str
    client_secret: str
    signing_secret: str
    web_token: str
    socket_token: str


class OpenAISettings(BaseSettings):
    """OpenAI API settings."""

    api_type: str = Field("azure")
    api_base: str
    api_version: str
    api_key: str


class OpenAIModelParams(BaseSettings):
    """Configurable parameters for an OpenAI LLM."""

    engine: str
    temperature: float = Field(0.0)
    top_p: float = Field(0.95)

    @property
    def type(self):
        return "ChatCompletion"


class AzureCSModelParams(BaseSettings):
    """Azure cognitive search model."""

    engine: str
    temperature: float = Field(0.2)
    top_p: float = Field(0.95)
    cs_key: str
    cs_endpoint: str
    restrict_answers_to_data: bool = Field(True)
    index_name: str
    semantic_configuration: str = Field("default")

    @property
    def type(self):
        return "ChatWithDataCompletion"


ModelParams = Union[OpenAIModelParams, AzureCSModelParams]


class Model(BaseSettings):
    """Language model."""

    name: str
    description: str
    params: ModelParams


class SentrySettings(BaseSettings):
    """Sentry settings."""

    dsn: str


class Config(BaseSettings):
    """Stats Chat Bot config."""
    
    log_level: str = Field("INFO", env="LOG_LEVEL")

    openai: OpenAISettings
    sentry: SentrySettings
    slack: SlackSettings
    tutor: TutorSettings
    models: list[Model]

    @model_validator
    def check_models(self):
        """Check that all referenced models are defined."""
        model_names = {m.name for m in self.models}
        # Make sure the "switch" model is defined
        if self.tutor.switch_model not in {m.name for m in self.models}:
            raise ValueError(f"Switch model {self.tutor.switch_model} is not defined.")

        # The switch model is a special case, so remove it from the list of
        # other models that are available.
        model_names.remove(self.tutor.switch_model)

        if not model_names:
            raise ValueError("Need at least 1 non-switch model.")

        for channel in self.tutor.channels:
            for model in channel.models:
                if model not in model_names:
                    if model == self.tutor.switch_model:
                        raise ValueError(f"Model {model} referenced in channel {channel} is the switch model and cannot be used in a channel.")
                    else:
                        raise ValueError(f"Model {model} referenced in channel {channel} is not defined.")

    def get_model(self, model_name: str) -> Model:
        """Get the config for a model.

        Args:
            model_name: Name of the model

        Returns:
            Config for the model
        """
        for model in self.models:
            if model.name == model_name:
                return model

        raise ValueError(f"Model {model_name} not defined.")

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

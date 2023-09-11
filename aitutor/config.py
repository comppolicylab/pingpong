import os
import tomllib
import logging
from pathlib import Path
from typing import Union, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

from .text import GREETING, DEFAULT_SYSTEM_PROMPT


logger = logging.getLogger(__name__)


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
    models: list[str] | None = Field(None)


class TutorSettings(BaseSettings):
    """Tutor settings."""

    default_prompt: Prompt
    channels: list[Channel]
    db_dir: str = Field(".db")
    switch_model: str = Field("switch")
    models: list[str]
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

    type: Literal["llm"]
    engine: str
    temperature: float = Field(0.0)
    top_p: float = Field(0.95)
    completion_type: Literal["ChatCompletion"] = Field("ChatCompletion")


class AzureCSModelParams(BaseSettings):
    """Azure cognitive search model."""

    type: Literal["csm"]
    engine: str
    temperature: float = Field(0.2)
    top_p: float = Field(0.95)
    cs_key: str
    cs_endpoint: str
    restrict_answers_to_data: bool = Field(True)
    index_name: str
    semantic_configuration: str = Field("default")
    completion_type: Literal["ChatWithDataCompletion"] = Field("ChatWithDataCompletion")


ModelParams = Union[OpenAIModelParams, AzureCSModelParams]


class Model(BaseSettings):
    """Language model."""

    name: str
    description: str
    examples: list[Example] = Field([])
    params: ModelParams = Field(..., discriminator="type")


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

    @model_validator(mode="after")
    def check_models(self) -> "Config":
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
            # The models can be defined in either the channel config or as
            # defaults in the tutor config. Only validate what will actually
            # be used. (This is a little redundant if there are multiple
            # channels that all use the tutor's default models, but it doesn't
            # make a difference for performance and it's simpler to think about
            # what's happening this way.)
            for model in (channel.models or self.tutor.models):
                if model not in model_names:
                    if model == self.tutor.switch_model:
                        raise ValueError(f"Model {model} referenced in channel {channel} is the switch model and cannot be used in a channel.")
                    else:
                        raise ValueError(f"Model {model} referenced in channel {channel} is not defined.")

        return self

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
                full_channel = channel.copy()
                # Fill in defaults in case they're missing
                prompt = self.tutor.default_prompt.dict()
                overrides = channel.prompt.dict() \
                        if isinstance(channel.prompt, Prompt) \
                        else (channel.prompt or {})
                prompt.update(overrides)
                full_channel.prompt = Prompt.parse_obj(prompt)
                full_channel.loading_reaction = (
                        channel.loading_reaction or self.tutor.loading_reaction
                        )
                full_channel.models = (
                        channel.models or self.tutor.models
                        )

                return full_channel

        return Channel(
                team_id="",
                channel_id="",
                loading_reaction=self.tutor.loading_reaction,
                prompt=self.tutor.default_prompt,
                models=self.tutor.models,
                )


def load_config(path: str = os.environ.get('CONFIG_PATH', "config.toml")):
    """Parse config file from path.

    Args:
        path (str, optional): Path to config file. Defaults to "config.toml".

    Returns:
        Config: Parsed config object.
    """
    logger.debug(f"Loading config from {path}")
    return Config.parse_obj(tomllib.loads(Path(path).read_text()))


# Globally available config object.
config = load_config()

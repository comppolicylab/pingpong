import os
import tomllib
import logging
from pathlib import Path
from typing import Union, Literal, Any

import tiktoken
from pydantic import Field, model_validator, field_validator
from pydantic_settings import BaseSettings

from .text import GREETING, SWITCH_PROMPT, DEFAULT_PROMPT
from .template import validate_template, format_template


logger = logging.getLogger(__name__)


class Example(BaseSettings):
    """Example chat turn for few-shot tuning."""

    user: str
    ai: str


class Prompt(BaseSettings):
    """Describe a prompt."""

    system: str = Field("")
    examples: list[Example] = Field([])
    variables: dict[str, str] = Field({})


class Engine(BaseSettings):
    """Language model engine."""

    name: str
    encoding: str
    capacity: int  # Number of tokens per minute
    context_size: int  # Max number of tokens that can be included in context
    concurrency: int = Field(5)  # Number of concurrent requests allowed
    response_tokens: int = Field(400)  # Number of tokens to hold out for response

    @field_validator("encoding")
    @classmethod
    def validate_encoding(cls, v: str) -> str:
        """Validate the encoding."""
        try:
            tiktoken.get_encoding(v)
        except Exception as e:
            raise ValueError(f"Invalid encoding {v}") from e
        return v


class OpenAIModelParams(BaseSettings):
    """Configurable parameters for an OpenAI LLM."""

    type: Literal["llm"]
    engine: Union[str, Engine]
    temperature: float = Field(0.0)
    top_p: float = Field(0.95)
    completion_type: Literal["ChatCompletion"] = Field("ChatCompletion")


class AzureCSModelParams(BaseSettings):
    """Azure cognitive search model."""

    type: Literal["csm"]
    engine: Union[str, Engine]
    temperature: float = Field(0.2)
    top_p: float = Field(0.95)
    threshold: float = Field(0.3)
    topNDocuments: int = Field(5, alias="top_n_documents")
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
    prompt: Prompt = Field(Prompt())

    def get_prompt(self, extra_vars: dict[str, str] | None = None) -> str:
        """Get the full prompt with template vars filled in.

        Args:
            extra_vars: Extra variables to fill in the template

        Returns:
            The full prompt with template variables filled in.
        """
        all_vars = self.prompt.variables.copy()
        if extra_vars:
            all_vars.update(extra_vars)
        return format_template(self.prompt.system, all_vars)


class ModelOverride(BaseSettings):
    """Override the default parameters for a model."""

    name: str
    params: dict[str, Any] = Field({})
    prompt: dict[str, Any] = Field({})


class Channel(BaseSettings):
    """Describe one slack channel integration."""

    team_id: str = Field("")
    channel_id: str
    loading_reaction: str = Field("")
    models: list[Union[str, ModelOverride, Model]] | None = Field(None)
    variables: dict[str, str] = Field({})


class Workspace(BaseSettings):
    """Describe one slack workspace integration."""

    team_id: str
    loading_reaction: str = Field("")
    models: list[Union[str, ModelOverride, Model]] | None = Field(None)
    channels: list[Channel] = Field([])
    variables: dict[str, str] = Field({})


class TutorSettings(BaseSettings):
    """Tutor settings."""

    workspaces: list[Workspace] = Field([])
    db_dir: str = Field(".db")
    switch_model: str = Field("switch")
    models: list[Union[str, ModelOverride, Model]]
    loading_reaction: str = Field("thinking_face")
    greeting: str = Field(GREETING)
    variables: dict[str, str] = Field({})

    @model_validator(mode="after")
    def check_greeting(self) -> "TutorSettings":
        """Validate the greeting template."""
        validate_template(self.greeting, self.variables)
        return self

    def get_greeting(self) -> str:
        """Get the greeting template."""
        return format_template(self.greeting, self.variables)


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


class SentrySettings(BaseSettings):
    """Sentry settings."""

    dsn: str


class MetricsSettings(BaseSettings):
    """Metrics settings."""

    connection_string: str = Field("")


class Config(BaseSettings):
    """Stats Chat Bot config."""
    
    log_level: str = Field("INFO", env="LOG_LEVEL")

    openai: OpenAISettings
    sentry: SentrySettings
    metrics: MetricsSettings = Field(MetricsSettings())
    slack: SlackSettings
    tutor: TutorSettings
    models: list[Model]
    engines: list[Engine] = Field([])

    @model_validator(mode="after")
    def check_engines(self) -> "Config":
        """Make sure that all model engines are defined.

        Turn all of the engine names as strings into Engine objects, as they
        are defined in the config.engines list.
        """
        engines = {e.name: e for e in self.engines}
        for m in self.models:
            if isinstance(m.params.engine, str):
                if m.params.engine not in engines:
                    raise ValueError(f"Engine {m.params.engine} is not defined.")
                m.params.engine = engines[m.params.engine]
        return self

    @model_validator(mode="after")
    def check_switch_model(self) -> "Config":
        """Check that all referenced models are defined."""
        model_names = {m.name for m in self.models}
        # Make sure the "switch" model is defined
        if self.tutor.switch_model not in model_names:
            raise ValueError(f"Switch model {self.tutor.switch_model} is not defined.")

        m = self.get_model(self.tutor.switch_model)
        # Fill in default switch prompt
        if not m.prompt.system:
            m.prompt.system = SWITCH_PROMPT

        return self

    @model_validator(mode="after")
    def check_model_overrides(self) -> "Config":
        """Validate and apply model overrides."""
        self.tutor.models = self._apply_model_overrides(
                self.tutor.models,
                self.tutor.variables)

        # Apply overrides to models for workspaces and channels.
        # Models themselves are each an independent definition at each level
        # of the hierarchy. So, if a list of two models is defined in the base
        # tutor level, and a list of one model is defined in a workspace, then
        # the workspace will only have that one single model it defined; it
        # will not inherit the other two models from the base tutor level.
        #
        # Variables, however, are inherited. So if a variable is defined in
        # the base tutor level, it will be available in all workspaces and
        # channels. If a variable is defined in a workspace, it will be
        # available in all channels in that workspace. Each level can override
        # variables defined above it. ModelOverrides can also override the
        # variables that are used in a prompt.
        #
        # When models and select other parameters are None, we *do* use
        # inheritance to fill in the missing value from the parent object.
        for workspace in self.tutor.workspaces:
            workspace.loading_reaction = (
                    workspace.loading_reaction or self.tutor.loading_reaction)
            if workspace.models is not None:
                workspace.models = self._apply_model_overrides(
                        workspace.models,
                        self.tutor.variables,
                        workspace.variables)
            else:
                workspace.models = self.tutor.models
            for channel in workspace.channels:
                channel.loading_reaction = (
                        channel.loading_reaction or workspace.loading_reaction)
                if channel.models is not None:
                    channel.models = self._apply_model_overrides(
                            channel.models,
                            self.tutor.variables,
                            workspace.variables,
                            channel.variables)
                else:
                    channel.models = workspace.models

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
        for workspace in self.tutor.workspaces:
            if workspace.team_id == team_id:
                for channel in workspace.channels:
                    if channel.channel_id == channel_id:
                        channel.team_id = team_id
                        return channel

                # Return default Channel for Workspace
                return Channel(
                        team_id=workspace.team_id,
                        channel_id=channel_id,
                        loading_reaction=workspace.loading_reaction,
                        models=workspace.models,
                        )

        # Return general default Channel
        return Channel(
                team_id=team_id,
                channel_id=channel_id,
                loading_reaction=self.tutor.loading_reaction,
                models=self.tutor.models,
                )

    def _apply_model_overrides(self,
                               overrides: list[str, ModelOverride, Model],
                               *dicts: dict[str, Any]) -> list[Model]:
        """Get a fully-specified list of models with overrides applied."""
        variables = {}
        for d in dicts:
            variables.update(d)

        models = list[Model]()
        for override in overrides:
            if isinstance(override, Model):
                new_vars = variables.copy()
                new_vars.update(override.prompt.variables)
                override.prompt.variables = new_vars
                models.append(override)
            elif isinstance(override, str):
                m = self.get_model(override).copy(deep=True)
                new_vars = variables.copy()
                new_vars.update(m.prompt.variables)
                m.prompt.variables = new_vars
                models.append(self.get_model(override))
            elif isinstance(override, ModelOverride):
                model = self.get_model(override.name).copy(deep=True)
                model.params = model.params.copy(update=override.params)
                new_vars = variables.copy()
                new_vars.update(override.prompt.get('variables', {}))
                override.prompt['variables'] = new_vars
                model.prompt = model.prompt.copy(update=override.prompt)
                models.append(model)
            else:
                raise ValueError(f"Unknown model override type {type(override)}")

        for m in models:
            if not m.prompt.system:
                m.prompt.system = DEFAULT_PROMPT
            validate_template(m.prompt.system, m.prompt.variables)
            if m.name == self.tutor.switch_model:
                raise ValueError(f"Switch model {self.tutor.switch_model} cannot be overridden.")

        return models


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

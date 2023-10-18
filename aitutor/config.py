import hashlib
import logging
import os
import time
import tomllib
import weakref
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Generic, Literal, TypeVar

import requests
import tiktoken
from pydantic import (
    Extra,
    Field,
    PrivateAttr,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic.v1.utils import deep_update
from pydantic_settings import BaseSettings
from sentry_sdk import capture_message

from .template import format_template, validate_template
from .text import DEFAULT_PROMPT, GREETING, TRIAGE_PROMPT

logger = logging.getLogger(__name__)


RefT = TypeVar("RefT", bound="BaseSettings")

# Cache of lock-related objects used for safely accessing/updating instances.
# These are not stored on the instances themselves so that we don't have to
# mess with Pydantic's deepcopy utils (Locks are not pickleable).
_LOCKS = weakref.WeakKeyDictionary["Ref", RLock]()


def _lock(obj: Any) -> RLock:
    """Get the lock for an object.

    A lock is created lazily for each object that needs one.
    """
    if obj not in _LOCKS:
        _LOCKS[obj] = RLock()
    return _LOCKS[obj]


class Ref(BaseSettings, Generic[RefT], extra=Extra.allow):  # type: ignore[call-arg]
    """Specify an external source for the configuration.

    When a field is defined with `Ref[T]` as a possible type, you can opt to
    move the parameters for `T` to an external source, either as a local file
    or a remote URL. The file will be loaded as TOML and parsed, with
    validation, according to type `T`.

    The `Ref[T]` instance can be used as a drop-in replacement for `T`; all
    attributes will be proxied to the underlying `T` instance.

    Any additional attributes used in the `Ref[T]` config will override the
    values in the external source.

    Use the `authorization` field to specify an authorization header to pass to
    remote resources, such as `Bearer <token>`.
    """

    ref__path__: str = Field(..., alias="ref", required=True)
    ref__authorization__: str | None = Field(None, alias="authorization")
    _instance: RefT = PrivateAttr()
    _hash: str = PrivateAttr("")

    def __init__(self, **kwargs: Any):
        """Initialize the ref."""
        super().__init__(**kwargs)
        self._hash = ""
        self._load()

    def __hash__(self) -> int:
        """Make the ref hashable based on what it refers to."""
        return hash((type(self), id(self)) + tuple(self.__dict__.values()))

    @model_serializer
    def dump(self) -> dict[str, Any] | None:
        """Dump the ref as a dictionary."""
        if not hasattr(self, "_instance") or not self._instance:
            return None
        return self._instance.model_dump()

    def _get_cls(self) -> type[RefT]:
        """Get the class used to parameterize the generic Ref."""
        # HACK(jnu): Reach into Pydantic internals to get the actual class
        # used to define the generic type. We'll use this to instantiate the
        # model instance after loading the raw data from the `ref` path.
        return self.__class__.__pydantic_generic_metadata__["args"][0]

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the referenced object."""
        # HACK(jnu): Reach into Pydantic internals to get the private attrs.
        with _lock(self):
            private = object.__getattribute__(self, "__pydantic_private__")
            if name.startswith("_"):
                return private[name]
            inst = private["_instance"]
            return getattr(inst, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Delegate attribute setting to the referenced object."""
        # HACK(jnu): Reach into Pydantic internals to get the private attrs.
        with _lock(self):
            private = object.__getattribute__(self, "__pydantic_private__")
            if name.startswith("_"):
                private[name] = value
                return
            inst = private["_instance"]
            setattr(inst, name, value)

    def _load(self):
        """Load the referenced object."""
        raw = self._load_raw()
        new_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        # Only update if the hash has changed
        if new_hash != self._hash:
            # Parse the raw data into a dictionary
            new_dict = tomllib.loads(raw)

            # Update the instance and hash
            with _lock(self):
                # HACK(jnu): Reach into Pydantic internals to get the extra attrs.
                extra = object.__getattribute__(self, "__pydantic_extra__")
                # Merge the extra attributes into the new config
                new_cfg = deep_update(new_dict, extra)
                # Parse the raw data into a new instance
                new_inst = self._get_cls().parse_obj(new_cfg)
                self._instance = new_inst
                self._hash = new_hash
                logger.info(f"Ref {self.ref__path__} updated to version {new_hash}")
        else:
            logger.debug(f"Ref {self.ref__path__} unchanged at {new_hash}")

    def _load_raw(self):
        """Load the referenced object."""
        # Load from remote URL
        if self.ref__path__.startswith("http://") or self.ref__path__.startswith(
            "https://"
        ):
            headers = {}
            if self.ref__authorization__:
                headers["Authorization"] = self.ref__authorization__
            resp = requests.get(self.ref__path__, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(f"Ref URL not found {self.ref__path__}")
            return resp.text
        else:
            # Otherwise assume ref is a local file
            if not os.path.exists(self.ref__path__):
                raise RuntimeError(f"Ref local file not found {self.ref__path__}")
            return Path(self.ref__path__).read_text()


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
    engine: str | Engine
    temperature: float = Field(0.0)
    top_p: float = Field(0.95)
    max_tokens: int | None = Field(None)
    completion_type: Literal["ChatCompletion"] = Field("ChatCompletion")


class ChromaModelParams(BaseSettings):
    """ChromaDB search model."""

    type: Literal["chroma"]
    engine: str | Engine
    collection: str
    dirs: list[str]
    temperature: float = Field(0.2)
    top_p: float = Field(0.95)
    topNDocuments: int = Field(5, alias="top_n_documents")
    completion_type: Literal["ChatWithChromaCompletion"] = Field(
        "ChatWithChromaCompletion"
    )


class AzureCSModelParams(BaseSettings):
    """Azure cognitive search model."""

    type: Literal["csm"]
    engine: str | Engine
    temperature: float = Field(0.2)
    top_p: float = Field(0.95)
    threshold: float = Field(0.3)
    topNDocuments: int = Field(5, alias="top_n_documents")
    cs_key: str
    cs_endpoint: str
    restrict_answers_to_data: bool = Field(True)
    index_name: str = Field("default")
    semantic_configuration: str = Field("default")
    completion_type: Literal["ChatWithDataCompletion"] = Field("ChatWithDataCompletion")


ModelParams = OpenAIModelParams | AzureCSModelParams | ChromaModelParams


class Model(BaseSettings):
    """Language model."""

    name: str
    description: str
    triage: list[Example] = Field([])
    params: ModelParams = Field(..., discriminator="type")
    prompt: Prompt = Field(Prompt())

    @property
    def engine(self) -> Engine:
        """Get the engine in a type-safe way."""
        engine = self.params.engine
        if not isinstance(engine, Engine):
            raise RuntimeError(f"Engine not initialized {engine}")
        return engine

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
    models: list[str | ModelOverride] | list[Model | Ref[Model]] | None = Field(None)
    variables: dict[str, str] = Field({})

    def get_models(self) -> list[Model | Ref[Model]]:
        """Access the models list in a type-safe way."""
        if self.models is None:
            return []

        models = list[Model | Ref[Model]]()
        for m in self.models:
            if not isinstance(m, Model) and not isinstance(m, Ref):
                raise RuntimeError(f"Model not initialized {m} ({type(m)})")
            models.append(m)
        return models


class Workspace(BaseSettings):
    """Describe one slack workspace integration."""

    team_id: str
    loading_reaction: str = Field("")
    models: list[str | ModelOverride] | list[Model | Ref[Model]] | None = Field(None)
    channels: list[Channel] = Field([])
    variables: dict[str, str] = Field({})


class TutorSettings(BaseSettings):
    """Tutor settings."""

    workspaces: list[Workspace | Ref[Workspace]] = Field([])
    db_dir: str = Field(".db")
    triage_model: str = Field("triage")
    models: list[str | ModelOverride | Ref[ModelOverride]] | list[Model | Ref[Model]]
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
    api_version: str | None = Field(None)
    api_key: str


class SentrySettings(BaseSettings):
    """Sentry settings."""

    dsn: str


class MetricsSettings(BaseSettings):
    """Metrics settings."""

    connection_string: str = Field("")


class DocumentIntelligenceSettings(BaseSettings):
    """Document Intelligence settings."""

    endpoint: str
    key: str


class Config(BaseSettings):
    """Stats Chat Bot config."""

    log_level: str = Field("INFO", env="LOG_LEVEL")

    reload: int = Field(0)
    openai: OpenAISettings
    di: DocumentIntelligenceSettings
    sentry: SentrySettings
    metrics: MetricsSettings = Field(MetricsSettings())
    slack: SlackSettings | list[SlackSettings]
    tutor: TutorSettings
    models: list[Model | Ref[Model]]
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
    def check_triage_model(self) -> "Config":
        """Check that all referenced models are defined."""
        model_names = {m.name for m in self.models}
        # Make sure the "triage" model is defined
        if self.tutor.triage_model not in model_names:
            raise ValueError(f"Triage model {self.tutor.triage_model} is not defined.")

        m = self.get_model(self.tutor.triage_model)
        # Fill in default triage prompt
        if not m.prompt.system:
            m.prompt.system = TRIAGE_PROMPT

        return self

    @model_validator(mode="after")
    def check_model_overrides(self) -> "Config":
        """Validate and apply model overrides."""
        self.tutor.models = self._apply_model_overrides(
            self.tutor.models, self.tutor.variables
        )

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
                workspace.loading_reaction or self.tutor.loading_reaction
            )
            if workspace.models is not None:
                workspace.models = self._apply_model_overrides(
                    workspace.models, self.tutor.variables, workspace.variables
                )
            else:
                workspace.models = self.tutor.models
            for channel in workspace.channels:
                channel.loading_reaction = (
                    channel.loading_reaction or workspace.loading_reaction
                )
                if channel.models is not None:
                    channel.models = self._apply_model_overrides(
                        channel.models,
                        self.tutor.variables,
                        workspace.variables,
                        channel.variables,
                    )
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

    def _apply_model_overrides(
        self,
        overrides: list[str | ModelOverride] | list[Model | Ref[Model]],
        *dicts: dict[str, Any],
    ) -> list[Model | Ref[Model]]:
        """Get a fully-specified list of models with overrides applied."""
        variables = {}
        for d in dicts:
            variables.update(d)

        models = list[Model | Ref[Model]]()
        for override in overrides:
            if isinstance(override, Model) or isinstance(override, Ref):
                new_override = override.copy(deep=True)
                new_override.prompt.variables.update(variables)
                models.append(new_override)
            elif isinstance(override, str):
                m = self.get_model(override).copy(deep=True)
                m.prompt.variables.update(variables)
                models.append(self.get_model(override))
            elif isinstance(override, ModelOverride):
                model = self.get_model(override.name).copy(deep=True)
                model.params = model.params.copy(update=override.params)
                new_vars = variables.copy()
                new_vars.update(override.prompt.get("variables", {}))
                override.prompt["variables"] = new_vars
                model.prompt = model.prompt.copy(update=override.prompt)
                models.append(model)
            else:
                raise ValueError(f"Unknown model override type {type(override)}")

        for m in models:
            if not m.prompt.system:
                m.prompt.system = DEFAULT_PROMPT
            validate_template(m.prompt.system, m.prompt.variables)
            if m.name == self.tutor.triage_model:
                raise ValueError(
                    f"Triage model {self.tutor.triage_model} cannot be overridden."
                )

        return models


# Find default location for config file.
DEFAULT_CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.toml")


class ConfigLoader:
    """Wrapper for Config that can periodically refresh it."""

    config: Config | None

    def __init__(self, path: str = DEFAULT_CONFIG_PATH) -> None:
        self.path = Path(path)
        self._last_load = 0.0
        self._last_hash = ""
        self.config = None

    def __call__(self) -> Config:
        self._check_reload()
        if not self.config:
            raise RuntimeError("Config not loaded yet")
        return self.config

    def load(self):
        """Parse config file from path."""
        logger.debug(f"Loading config from {self.path}")
        if not self.path.exists():
            logger.warning("Config {self.path} does not exist")
            return
        raw = self.path.read_text()
        self.config = Config.parse_obj(tomllib.loads(raw))
        self._last_load = time.monotonic()
        new_hash = hashlib.sha256(
            self.config.model_dump_json().encode("utf-8")
        ).hexdigest()

        # Configure logging
        logging.basicConfig(level=self.config.log_level)
        # Shut up some noisy libraries
        logging.getLogger("azure.monitor.opentelemetry").setLevel(logging.WARNING)
        logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
            logging.WARNING
        )
        logging.getLogger("urllib3").setLevel(logging.WARNING)

        if new_hash != self._last_hash:
            self._last_hash = new_hash
            logger.info(f"Config updated to {new_hash} at {self._last_load}")
            capture_message(f"Config updated to {new_hash} at {self._last_load}")

    def _check_reload(self) -> None:
        """Refresh the configuration."""
        if not self.config:
            self.load()
            return
        try:
            if not self.config.reload:
                return
            now = time.monotonic()
            if now - self._last_load > self.config.reload:
                self.load()
        except Exception as e:
            logger.error(f"Error reloading config: {e}")


T = TypeVar("T")


class ReadOnlyFunctorProxy(Generic[T]):
    def __init__(self, f: Callable[[], T]) -> None:
        self._f = f

    def __getattr__(self, name: str) -> Any:
        return getattr(self._f(), name)


# Globally available config object.
config = ReadOnlyFunctorProxy(ConfigLoader())

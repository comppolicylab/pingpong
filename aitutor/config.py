import hashlib
import logging
import os
import time
import tomllib
import weakref
from functools import cached_property
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Generic, Literal, TypeVar, Union

import requests
from pydantic import Extra, Field, PrivateAttr, model_serializer
from pydantic.v1.utils import deep_update
from pydantic_settings import BaseSettings
from sentry_sdk import capture_message

from .db import PostgresDriver
from .email import AzureEmailSender, GmailEmailSender

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


class AzureEmailSettings(BaseSettings):
    type: Literal["azure"]
    from_address: str
    endpoint: str
    access_key: str

    @property
    def sender(self) -> AzureEmailSender:
        return AzureEmailSender(self.from_address, self.connection_string)

    @property
    def connection_string(self) -> str:
        return f"endpoint={self.endpoint};accessKey={self.access_key}"


class GmailEmailSettings(BaseSettings):
    type: Literal["gmail"]
    from_address: str
    password: str

    @property
    def sender(self) -> GmailEmailSender:
        return GmailEmailSender(self.from_address, self.password)


EmailSettings = Union[AzureEmailSettings, GmailEmailSettings]


class SentrySettings(BaseSettings):
    """Sentry settings."""

    dsn: str


class MetricsSettings(BaseSettings):
    """Metrics settings."""

    connection_string: str = Field("")


class SecretKey(BaseSettings):
    """Secret key."""

    key: str
    algorithm: str = Field("HS256")


class AuthSettings(BaseSettings):
    secret_keys: list[SecretKey]


class PostgresSettings(BaseSettings):
    """Settings for connecting to Postgres."""

    engine: Literal["postgres"]
    host: str = Field("localhost")
    port: int = Field(5432)
    user: str = Field("postgres")
    password: str
    database: str = Field("aitutor")

    @cached_property
    def driver(self) -> PostgresDriver:
        url = f"{self.user}:{self.password}@{self.host}" f":{self.port}/{self.database}"
        return PostgresDriver(url)


DbSettings = PostgresSettings


class Config(BaseSettings):
    """Stats Chat Bot config."""

    log_level: str = Field("INFO", env="LOG_LEVEL")

    reload: int = Field(0)
    public_url: str = Field("http://localhost:8000")

    development: bool = Field(False, env="DEVELOPMENT")
    db: DbSettings
    auth: AuthSettings
    email: EmailSettings
    sentry: SentrySettings
    metrics: MetricsSettings = Field(MetricsSettings())

    def url(self, path: str | None) -> str:
        """Return a URL relative to the public URL."""
        if not path:
            return self.public_url
        return f"{self.public_url.rstrip('/')}/{path.lstrip('/')}"


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
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
            logging.WARNING
        )
        if self.config.log_level != "DEBUG":
            logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

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

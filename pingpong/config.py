import logging
import os
import tomllib
from functools import cached_property
from pathlib import Path
from typing import Literal, Union

from pydantic import Field
from pydantic_settings import BaseSettings

from .db import PostgresDriver, SqliteDriver
from .email import AzureEmailSender, GmailEmailSender, SmtpEmailSender
from .support import DiscordSupportDriver

logger = logging.getLogger(__name__)


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


class SmtpEmailSettings(BaseSettings):
    type: Literal["smtp"]
    from_address: str
    host: str
    port: int = Field(587)
    username: str | None = Field(None)
    password: str | None = Field(None)
    use_tls: bool = Field(True)
    start_tls: bool = Field(False)
    use_ssl: bool = Field(False)

    @property
    def sender(self) -> SmtpEmailSender:
        return SmtpEmailSender(
            self.from_address,
            host=self.host,
            port=self.port,
            user=self.username,
            pw=self.password,
            use_tls=self.use_tls,
            start_tls=self.start_tls,
            use_ssl=self.use_ssl,
        )


EmailSettings = Union[AzureEmailSettings, GmailEmailSettings, SmtpEmailSettings]


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
    database: str = Field("pingpong")
    maintenance_db: str | None = Field(None)

    @cached_property
    def driver(self) -> PostgresDriver:
        url = f"{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        return PostgresDriver(url, maintenance_db=self.maintenance_db)


class SqliteSettings(BaseSettings):
    """Settings for connecting to SQLite."""

    engine: Literal["sqlite"]
    path: str = Field("db.sqlite3")

    @cached_property
    def driver(self) -> SqliteDriver:
        return SqliteDriver(self.path)


DbSettings = Union[PostgresSettings, SqliteSettings]


class InitSettings(BaseSettings):
    """Settings for first-time app init."""

    super_users: list[str] = Field([])


class DiscordSettings(BaseSettings):
    """Settings for getting help with Discord."""

    type: Literal["discord"]
    webhook: str
    invite: str

    def blurb(self) -> str:
        return (
            f'We run a <a href="{self.invite}" '
            'rel="noopener noreferrer" target="_blank">'
            "Discord server</a> where you can get help with PingPong."
        )

    @cached_property
    def driver(self) -> DiscordSupportDriver:
        return DiscordSupportDriver(self.webhook)


class NoSupportSettings(BaseSettings):
    type: Literal["none"]

    def blurb(self) -> str:
        return "We sadly cannot offer additional support for this app right now."

    @cached_property
    def driver(self) -> None:
        return None


SupportSettings = Union[DiscordSettings, NoSupportSettings]


class UploadSettings(BaseSettings):
    """Settings for file uploads."""

    private_file_max_size: int = Field(10 * 1024 * 1024)  # 10 MB
    class_file_max_size: int = Field(512 * 1024 * 1024)  # 512 MB


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
    init: InitSettings = Field(InitSettings())
    support: SupportSettings = Field(NoSupportSettings(type="none"))
    upload: UploadSettings = Field(UploadSettings())

    def url(self, path: str | None) -> str:
        """Return a URL relative to the public URL."""
        if not path:
            return self.public_url
        return f"{self.public_url.rstrip('/')}/{path.lstrip('/')}"


def _load_config():
    """Load the config from the config file."""
    # Find default location for config file.
    _cfg_path = os.environ.get("CONFIG_PATH", "config.toml")

    # Read the raw config file.
    _raw_cfg = Path(_cfg_path).read_text()

    try:
        return Config.parse_obj(tomllib.loads(_raw_cfg))
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        raise


# Globally available config object.
config = _load_config()

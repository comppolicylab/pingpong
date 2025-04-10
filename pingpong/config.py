import base64
import logging
import os
import tomllib
from functools import cached_property
from pathlib import Path
from typing import Literal, Union

from glowplug import PostgresSettings, SqliteSettings
from pydantic import Field
from pydantic_settings import BaseSettings

from pingpong.artifacts import LocalArtifactStore, S3ArtifactStore
from pingpong.log_filters import IgnoreHealthEndpoint
from .authz import OpenFgaAuthzDriver
from .email import AzureEmailSender, GmailEmailSender, MockEmailSender, SmtpEmailSender
from .support import SupportSettings, NoSupportSettings

logger = logging.getLogger(__name__)


class OpenFgaAuthzSettings(BaseSettings):
    """Settings for OpenFGA authorization."""

    type: Literal["openfga"]
    scheme: str = Field("http")
    host: str = Field("localhost")
    port: int = Field(8080)
    store: str = Field("pingpong")
    cfg: str = Field("authz.json")
    key: str | None = Field(None)
    verify_ssl: bool = Field(True)

    @cached_property
    def driver(self):
        return OpenFgaAuthzDriver(
            scheme=self.scheme,
            host=f"{self.host}:{self.port}",
            store=self.store,
            key=self.key,
            model_config=self.cfg,
            verify_ssl=self.verify_ssl,
        )


AuthzSettings = Union[OpenFgaAuthzSettings]


class MockEmailSettings(BaseSettings):
    type: Literal["mock"]

    @cached_property
    def sender(self) -> MockEmailSender:
        return MockEmailSender()


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


EmailSettings = Union[
    AzureEmailSettings, GmailEmailSettings, SmtpEmailSettings, MockEmailSettings
]


class SentrySettings(BaseSettings):
    """Sentry settings."""

    dsn: str = Field("")


class MetricsSettings(BaseSettings):
    """Metrics settings."""

    connection_string: str = Field("")


class SecretKey(BaseSettings):
    """Secret key."""

    key: str
    algorithm: str = Field("HS256")


class BaseAuthnSettings(BaseSettings):
    name: str
    domains: list[str] = Field(["*"])
    excluded_domains: list[str] = Field([])


class Saml2AuthnSettings(BaseAuthnSettings):
    method: Literal["sso"]
    protocol: Literal["saml"]
    provider: str
    base_path: str = Field("saml")


class MagicLinkAuthnSettings(BaseAuthnSettings):
    method: Literal["magic_link"]
    expiry: int = Field(86_400)


AuthnSettings = Union[Saml2AuthnSettings, MagicLinkAuthnSettings]


class AuthSettings(BaseSettings):
    """Authentication and related configuration."""

    autopromote_on_login: bool = Field(False)
    secret_keys: list[SecretKey]
    authn_methods: list[AuthnSettings]


DbSettings = Union[PostgresSettings, SqliteSettings]


class CanvasSettings(BaseSettings):
    """Connection settings to a Canvas instance."""

    type: Literal["canvas"]
    tenant: str
    client_id: str
    client_secret: str
    base_url: str
    sso_target: str | None = Field(None)
    sso_tenant: str | None = Field(None)
    sync_wait: int = Field(60 * 10)  # 10 mins
    auth_token_expiry: int = Field(60 * 60)  # 1 hour

    def url(self, path: str) -> str:
        """Return a URL relative to the Canvas Base URL."""
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def auth_link(self, token: str) -> str:
        """Return the Redirect URL for Canvas authentication.

        Args:
            token (str): The generated `AuthToken` identifying the authentication request. This will be returned by Canvas.

        Returns:
            str: Redirect URL.
        """
        return self.url(
            f"/login/oauth2/auth?client_id={self.client_id}&response_type=code&redirect_uri={config.url('/api/v1/auth/canvas')}&state={token}"
        )


LMSInstance = Union[CanvasSettings]


class LMSSettings(BaseSettings):
    """LMS connection settings."""

    lms_instances: list[LMSInstance]


class InitSettings(BaseSettings):
    """Settings for first-time app init."""

    super_users: list[str] = Field([])


class UploadSettings(BaseSettings):
    """Settings for file uploads."""

    private_file_max_size: int = Field(512 * 1024 * 1024)  # 512 MB
    class_file_max_size: int = Field(512 * 1024 * 1024)  # 512 MB


class S3StoreSettings(BaseSettings):
    """Settings for S3 storage."""

    type: Literal["s3"] = "s3"
    save_target: str
    download_link_expiration: int = Field(60 * 60, gt=0, le=86400)  # 1 hour

    @cached_property
    def store(self):
        return S3ArtifactStore(self.save_target)


class LocalStoreSettings(BaseSettings):
    """Settings for S3 storage."""

    type: Literal["local"] = "local"
    save_target: str
    download_link_expiration: int = Field(60 * 60, gt=0, le=86400)  # 1 hour

    @cached_property
    def store(self):
        return LocalArtifactStore(self.save_target)


ArtifactStoreSettings = Union[S3StoreSettings, LocalStoreSettings]


class Config(BaseSettings):
    """Stats Chat Bot config."""

    log_level: str = Field("INFO", env="LOG_LEVEL")
    realtime_log_level: str = Field("INFO", env="REALTIME_LOG_LEVEL")

    reload: int = Field(0)
    public_url: str = Field("http://localhost:8000")
    development: bool = Field(False, env="DEVELOPMENT")
    artifact_store: ArtifactStoreSettings = LocalStoreSettings(save_target="uploads")
    db: DbSettings
    auth: AuthSettings
    authz: AuthzSettings
    email: EmailSettings
    lms: LMSSettings
    sentry: SentrySettings = Field(SentrySettings())
    metrics: MetricsSettings = Field(MetricsSettings())
    init: InitSettings = Field(InitSettings())
    support: SupportSettings = Field(NoSupportSettings())
    upload: UploadSettings = Field(UploadSettings())

    def url(self, path: str | None) -> str:
        """Return a URL relative to the public URL."""
        if not path:
            return self.public_url
        return f"{self.public_url.rstrip('/')}/{path.lstrip('/')}"


def _load_config() -> Config:
    """Load the config either from a file or an environment variable.

    Can read the config as a base64-encoded string from the CONFIG env variable,
    or from the file specified in the CONFIG_PATH variable.

    The CONFIG variable takes precedence over the CONFIG_PATH variable.

    Returns:
        Config: The loaded config.
    """
    _direct_cfg = os.environ.get("CONFIG", None)
    _cfg_path = os.environ.get("CONFIG_PATH", "config.toml")

    _raw_cfg: None | str = None

    if _direct_cfg:
        # If the config is provided directly, use it.
        # It should be encoded as Base64.
        _raw_cfg = base64.b64decode(_direct_cfg).decode("utf-8")
    else:
        # Otherwise read the config from the specified file.
        _raw_cfg = Path(_cfg_path).read_text()

    if not _raw_cfg:
        raise ValueError("No config provided")

    try:
        return Config.model_validate(tomllib.loads(_raw_cfg))
    except Exception as e:
        logger.exception(f"Error loading config: {e}")
        raise


# Globally available config object.
config = _load_config()


# Configure logging, shutting up some noisy libraries
logging.basicConfig(level=config.log_level)
# Shut up some noisy libraries
logging.getLogger("azure.monitor.opentelemetry").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
    logging.WARNING
)
logging.getLogger("uvicorn.access").addFilter(IgnoreHealthEndpoint())
logging.getLogger("realtime_browser").setLevel(config.realtime_log_level)
logging.getLogger("realtime_openai").setLevel(config.realtime_log_level)
if config.log_level != "DEBUG":
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

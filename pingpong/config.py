import base64
import logging
import os
import tomllib
from functools import cached_property
from pathlib import Path
from typing import Any, Literal, Union
from urllib.parse import urlsplit

from glowplug import PostgresSettings, SqliteSettings
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from pingpong.artifacts import LocalArtifactStore, S3ArtifactStore
from pingpong.audio_store import LocalAudioStore, S3AudioStore
from pingpong.video_store import LocalVideoStore, S3VideoStore
from pingpong.log_filters import IgnoreHealthEndpoint
from .authz import OpenFgaAuthzDriver
from .email import AzureEmailSender, GmailEmailSender, MockEmailSender, SmtpEmailSender
from .lti import AWSLTIKeyStore, LocalLTIKeyStore, LTIKeyManager
from .support import SupportSettings, NoSupportSettings

logger = logging.getLogger(__name__)

LEGACY_OPENID_CONFIGURATION_PATHS_DEFAULTS = (
    "/.well-known/openid-configuration",
    "/.well-known/openid",
    "/api/lti/security/openid-configuration",
)


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
    tenant_friendly_name: str
    client_id: str
    client_secret: str
    base_url: str
    sso_target: str | None = Field(None)
    sso_tenant: str | None = Field(None)
    require_sso: bool = Field(True)
    ignore_incomplete_profiles: bool = Field(False)
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


class PanoptoTenantSettings(BaseSettings):
    """One Panopto tenant (hostname + OAuth2 credentials)."""

    tenant: str
    tenant_friendly_name: str
    host: str
    client_id: str
    client_secret: str


class PanoptoConnectorSettings(BaseSettings):
    """Panopto connector configuration."""

    tenants: list[PanoptoTenantSettings] = Field([])

    def tenant(self, tenant_id: str) -> PanoptoTenantSettings | None:
        for t in self.tenants:
            if t.tenant == tenant_id:
                return t
        return None


class ConnectorsSettings(BaseSettings):
    """Third-party service connector configuration."""

    panopto: PanoptoConnectorSettings = Field(PanoptoConnectorSettings())


class InitSettings(BaseSettings):
    """Settings for first-time app init."""

    super_users: list[str] = Field([])


class UploadSettings(BaseSettings):
    """Settings for file uploads."""

    private_file_max_size: int = Field(512 * 1024 * 1024)  # 512 MB
    class_file_max_size: int = Field(512 * 1024 * 1024)  # 512 MB
    lecture_video_max_size: int = Field(512 * 1024 * 1024)  # 512 MB


class S3StoreSettings(BaseSettings):
    """Settings for S3 storage."""

    type: Literal["s3"] = "s3"
    save_target: str
    download_link_expiration: int = Field(60 * 60, gt=0, le=86400)  # 1 hour

    @cached_property
    def store(self):
        return S3ArtifactStore(self.save_target)


class LocalStoreSettings(BaseSettings):
    """Settings for local storage."""

    type: Literal["local"] = "local"
    save_target: str
    download_link_expiration: int = Field(60 * 60, gt=0, le=86400)  # 1 hour

    @cached_property
    def store(self):
        return LocalArtifactStore(self.save_target)


ArtifactStoreSettings = Union[S3StoreSettings, LocalStoreSettings]


class S3VideoStoreSettings(BaseSettings):
    """Settings for S3 Video Store"""

    type: Literal["s3"] = "s3"
    save_target: str
    allow_unsigned: bool = Field(False)

    @cached_property
    def store(self):
        return S3VideoStore(bucket=self.save_target, allow_unsigned=self.allow_unsigned)


class LocalVideoStoreSettings(BaseSettings):
    """Settings for Local Video Store"""

    type: Literal["local"] = "local"
    save_target: str

    @cached_property
    def store(self):
        return LocalVideoStore(directory=self.save_target)


VideoStoreSettings = Union[S3VideoStoreSettings, LocalVideoStoreSettings]


class S3AudioStoreSettings(BaseSettings):
    """Settings for S3 storage."""

    type: Literal["s3"] = "s3"
    save_target: str

    @cached_property
    def store(self):
        return S3AudioStore(self.save_target)


class LocalAudioStoreSettings(BaseSettings):
    """Settings for local storage."""

    type: Literal["local"] = "local"
    save_target: str

    @cached_property
    def store(self):
        return LocalAudioStore(self.save_target)


AudioStoreSettings = Union[S3AudioStoreSettings, LocalAudioStoreSettings]


class AWSLTIKeyStoreSettings(BaseSettings):
    """Settings for AWS LTI key store."""

    type: Literal["aws"] = "aws"
    secret_name: str

    @cached_property
    def key_manager(self):
        key_store = AWSLTIKeyStore(self.secret_name)
        return LTIKeyManager(key_store)


class LocalLTIKeyStoreSettings(BaseSettings):
    """Settings for local LTI key store."""

    type: Literal["local"] = "local"
    directory: str

    @cached_property
    def key_manager(self):
        key_store = LocalLTIKeyStore(self.directory)
        return LTIKeyManager(key_store)


LTIKeyStoreSettings = Union[AWSLTIKeyStoreSettings, LocalLTIKeyStoreSettings]


class LTIAllowDenySettings(BaseSettings):
    """Allow/deny pattern settings for LTI security checks."""

    allow: list[str] = Field(["*"])
    deny: list[str] = Field([])


class LTIUrlSecuritySettings(BaseSettings):
    """Security allow/deny settings for URLs."""

    allow_http_in_development: bool | None = Field(None)
    allow_redirects: bool | None = Field(None)
    hosts: LTIAllowDenySettings | None = Field(None)
    paths: LTIAllowDenySettings | None = Field(None)


class LTISecuritySettings(BaseSettings):
    """LTI security settings."""

    allow_http_in_development: bool = Field(True)
    allow_redirects: bool = Field(True)
    hosts: LTIAllowDenySettings = Field(LTIAllowDenySettings())
    paths: LTIAllowDenySettings = Field(LTIAllowDenySettings())

    authorization_endpoint: LTIUrlSecuritySettings = Field(LTIUrlSecuritySettings())
    names_and_role_endpoint: LTIUrlSecuritySettings = Field(LTIUrlSecuritySettings())
    jwks_uri: LTIUrlSecuritySettings = Field(LTIUrlSecuritySettings())
    registration_endpoint: LTIUrlSecuritySettings = Field(LTIUrlSecuritySettings())
    openid_configuration: LTIUrlSecuritySettings = Field(LTIUrlSecuritySettings())
    token_endpoint: LTIUrlSecuritySettings = Field(LTIUrlSecuritySettings())


class LTISettings(BaseSettings):
    """LTI Advantage Service settings."""

    key_store: LTIKeyStoreSettings
    sync_wait: int = Field(60 * 10, gt=0)  # 10 mins
    security: LTISecuritySettings = Field(LTISecuritySettings())

    # Key rotation settings
    rotation_schedule: str = Field("0 0 1 * *")  # First day of every month at midnight
    key_retention_count: int = Field(3)  # Keep last 3 keys
    key_size: int = Field(2048)  # RSA key size in bits

    @staticmethod
    def _validate_legacy_openid_configuration_paths(
        openid_configuration_paths: object,
    ) -> list[str]:
        if not isinstance(openid_configuration_paths, dict):
            raise TypeError(
                "lti.openid_configuration_paths must be an object with mode and paths"
            )

        mode = openid_configuration_paths.get("mode", "replace")
        if mode not in {"append", "replace"}:
            raise ValueError(
                "lti.openid_configuration_paths.mode must be either 'append' or 'replace'"
            )

        raw_paths = openid_configuration_paths.get(
            "paths", list(LEGACY_OPENID_CONFIGURATION_PATHS_DEFAULTS)
        )
        if not isinstance(raw_paths, list):
            raise ValueError("lti.openid_configuration_paths.paths must be a list")

        normalized_paths: list[str] = []
        for raw_path in raw_paths:
            if not isinstance(raw_path, str):
                raise ValueError(
                    "lti.openid_configuration_paths.paths must contain only strings"
                )

            path = raw_path.strip()
            if not path or not path.startswith("/") or "?" in path or "#" in path:
                raise ValueError(
                    "lti.openid_configuration_paths.paths entries must be absolute URL paths "
                    "without query or fragment"
                )
            normalized_paths.append(path)

        if mode == "append":
            merged_paths = [
                *LEGACY_OPENID_CONFIGURATION_PATHS_DEFAULTS,
                *normalized_paths,
            ]
            return list(dict.fromkeys(merged_paths))

        return normalized_paths

    @staticmethod
    def _validate_legacy_dev_http_hosts(dev_http_hosts: object) -> list[str]:
        if not isinstance(dev_http_hosts, list):
            raise ValueError("lti.dev_http_hosts must be a list")

        normalized_hosts: list[str] = []
        for host in dev_http_hosts:
            if not isinstance(host, str):
                raise ValueError("lti.dev_http_hosts entries must be strings")
            if host.strip():
                normalized_hosts.append(host.strip().lower())
        return normalized_hosts

    @staticmethod
    def _validate_legacy_platform_url_allowlist(
        platform_url_allowlist: object,
    ) -> list[str]:
        if not isinstance(platform_url_allowlist, list):
            raise ValueError("lti.platform_url_allowlist must be a list")

        normalized_hosts: list[str] = []
        for entry in platform_url_allowlist:
            if not isinstance(entry, str):
                raise ValueError("lti.platform_url_allowlist entries must be strings")

            value = entry.strip().lower()
            if not value:
                raise ValueError("lti.platform_url_allowlist entries must not be empty")
            if value.startswith("*."):
                raise ValueError(
                    "lti.platform_url_allowlist entries must be exact hosts or URLs"
                )

            if "://" in value:
                parsed = urlsplit(value)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    raise ValueError(
                        "lti.platform_url_allowlist URL entries must use http or https"
                    )
                value = parsed.hostname.lower()
            elif "/" in value or ":" in value:
                raise ValueError(
                    "lti.platform_url_allowlist entries must be hostnames or URLs"
                )

            normalized_hosts.append(value)

        return normalized_hosts

    @staticmethod
    def _mutable_dict(value: object, *, field_name: str) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dict(dumped)
        raise ValueError(f"{field_name} must be an object")

    @model_validator(mode="before")
    @classmethod
    def _map_legacy_security_settings(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        legacy_keys = [
            key
            for key in (
                "platform_url_allowlist",
                "openid_configuration_paths",
                "dev_http_hosts",
            )
            if key in data
        ]
        if not legacy_keys:
            return data

        mapped_data = dict(data)
        platform_url_allowlist = mapped_data.pop("platform_url_allowlist", None)
        openid_configuration_paths = mapped_data.pop("openid_configuration_paths", None)
        dev_http_hosts = mapped_data.pop("dev_http_hosts", None)
        using_legacy_layout = "security" not in data
        explicit_openid_paths = (
            isinstance(data.get("security"), dict)
            and isinstance(data["security"].get("openid_configuration"), dict)
            and "paths" in data["security"]["openid_configuration"]
        )
        explicit_global_paths = (
            isinstance(data.get("security"), dict)
            and isinstance(data["security"].get("paths"), dict)
            and "allow" in data["security"]["paths"]
        )

        if "security" in mapped_data:
            security = cls._mutable_dict(
                mapped_data["security"], field_name="lti.security"
            )
        else:
            security = {}

        if "hosts" in security:
            hosts = cls._mutable_dict(
                security["hosts"],
                field_name="lti.security.hosts",
            )
        else:
            hosts = {}

        if "paths" in security:
            paths = cls._mutable_dict(
                security["paths"],
                field_name="lti.security.paths",
            )
        else:
            paths = {}

        openid_configuration = cls._mutable_dict(
            security.get("openid_configuration", {}),
            field_name="lti.security.openid_configuration",
        )
        if "paths" in openid_configuration:
            openid_paths = cls._mutable_dict(
                openid_configuration["paths"],
                field_name="lti.security.openid_configuration.paths",
            )
        else:
            openid_paths = {}

        normalized_dev_http_hosts: list[str] | None = None
        if dev_http_hosts is not None and "allow_http_in_development" not in security:
            normalized_dev_http_hosts = cls._validate_legacy_dev_http_hosts(
                dev_http_hosts
            )
        normalized_platform_url_allowlist: list[str] | None = None
        if platform_url_allowlist is not None and "allow" not in hosts:
            normalized_platform_url_allowlist = (
                cls._validate_legacy_platform_url_allowlist(platform_url_allowlist)
            )

        legacy_host_allow = []
        if normalized_platform_url_allowlist is not None:
            legacy_host_allow.extend(normalized_platform_url_allowlist)

        if legacy_host_allow and "allow" not in hosts:
            hosts["allow"] = list(dict.fromkeys(legacy_host_allow))

        if openid_configuration_paths is not None and "allow" not in openid_paths:
            openid_paths["allow"] = cls._validate_legacy_openid_configuration_paths(
                openid_configuration_paths
            )
        elif (
            using_legacy_layout
            or (not explicit_openid_paths and not explicit_global_paths)
        ) and "allow" not in openid_paths:
            # Legacy configs defaulted to these explicit discovery paths.
            openid_paths["allow"] = list(LEGACY_OPENID_CONFIGURATION_PATHS_DEFAULTS)

        if "allow_http_in_development" not in security:
            if dev_http_hosts is not None:
                security["allow_http_in_development"] = bool(normalized_dev_http_hosts)
            elif using_legacy_layout:
                # Legacy configs defaulted to HTTP being allowed in development.
                security["allow_http_in_development"] = True

        security["hosts"] = hosts
        security["paths"] = paths
        openid_configuration["paths"] = openid_paths
        security["openid_configuration"] = openid_configuration
        mapped_data["security"] = security

        for key in legacy_keys:
            if key == "platform_url_allowlist":
                logger.warning(
                    "Deprecated config key 'lti.platform_url_allowlist' used. "
                    "It will be removed in PingPong 8.0. "
                    "Replace with:\n"
                    "  [lti.security.hosts]\n"
                    "  allow = %r",
                    hosts.get("allow", ["*"]),
                )
            elif key == "openid_configuration_paths":
                logger.warning(
                    "Deprecated config key 'lti.openid_configuration_paths' used. "
                    "It will be removed in PingPong 8.0. "
                    "Replace with:\n"
                    "  [lti.security.openid_configuration.paths]\n"
                    "  allow = %r",
                    openid_paths.get(
                        "allow", list(LEGACY_OPENID_CONFIGURATION_PATHS_DEFAULTS)
                    ),
                )
            elif key == "dev_http_hosts":
                logger.warning(
                    "Deprecated config key 'lti.dev_http_hosts' used. "
                    "It will be removed in PingPong 8.0. "
                    "Replace with:\n"
                    "  [lti.security]\n"
                    "  allow_http_in_development = %r\n"
                    "  [lti.security.hosts]\n"
                    "  allow = %r",
                    security.get("allow_http_in_development", True),
                    hosts.get("allow", ["*"]),
                )

        return mapped_data


class FeatureFlags(BaseSettings):
    """Feature flags for the application."""

    # Feature flags
    lecture_video_elevenlabs_only_mode: bool = Field(False)


class Config(BaseSettings):
    """Stats Chat Bot config."""

    model_config = SettingsConfigDict(case_sensitive=False)

    log_level: str = Field("INFO")
    realtime_log_level: str | None = Field(None)
    realtime_recorder_log_level: str | None = Field(
        None, validation_alias="REALTIME_LOGGER_LOG_LEVEL"
    )
    prompt_randomizer_log_level: str | None = Field(None)
    responses_api_log_level: str | None = Field(None)
    feature_flags: FeatureFlags = Field(FeatureFlags())

    reload: int = Field(0)
    public_url: str = Field("http://localhost:8000")
    development: bool = Field(False)
    artifact_store: ArtifactStoreSettings = LocalStoreSettings(
        save_target="local_exports/thread_exports"
    )
    file_store: ArtifactStoreSettings = LocalStoreSettings(
        save_target="local_exports/files"
    )
    audio_store: AudioStoreSettings = LocalAudioStoreSettings(
        save_target="local_exports/voice_mode_recordings"
    )
    lecture_video_audio_store: AudioStoreSettings = LocalAudioStoreSettings(
        save_target="local_exports/lecture_video_narrations"
    )
    video_store: VideoStoreSettings | None = Field(None)
    db: DbSettings
    auth: AuthSettings
    authz: AuthzSettings
    email: EmailSettings
    lms: LMSSettings
    lti: LTISettings | None = Field(None)
    connectors: ConnectorsSettings = Field(ConnectorsSettings())
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
logging.getLogger("realtime_browser").setLevel(
    config.realtime_log_level or config.log_level
)
logging.getLogger("realtime_openai").setLevel(
    config.realtime_log_level or config.log_level
)
logging.getLogger("audio_recorder").setLevel(
    config.realtime_recorder_log_level or config.realtime_log_level or config.log_level
)
logging.getLogger("prompt_randomizer").setLevel(
    config.prompt_randomizer_log_level or config.log_level
)
logging.getLogger("responses_api_transition").setLevel(
    config.responses_api_log_level or config.log_level
)
if config.log_level != "DEBUG":
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

import os
from collections.abc import Mapping
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CLOUD_MARKERS = (
    "WEBSITE_INSTANCE_ID",
    "WEBSITE_SITE_NAME",
    "CONTAINER_APP_NAME",
    "CONTAINER_APP_REVISION",
    "KUBERNETES_SERVICE_HOST",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", populate_by_name=True)

    app_environment: Literal["local", "test", "production"] = "local"
    repository_backend: Literal["memory", "sql"] = "memory"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    cors_allow_origins: tuple[str, ...] = ()
    log_level: Literal["info", "warning", "error"] = "info"
    sql_server: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
    sql_database: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    managed_identity_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MANAGED_IDENTITY_CLIENT_ID", "AZURE_CLIENT_ID"),
    )
    sql_pool_size: int = Field(default=5, ge=1, le=100)
    sql_pool_max_overflow: int = Field(default=0, ge=0, le=100)
    sql_pool_timeout_seconds: float = Field(default=2, gt=0, le=60)
    sql_pool_recycle_seconds: int = Field(default=1500, ge=30, le=3600)
    sql_login_timeout_seconds: int = Field(default=5, ge=1, le=60)
    sql_command_timeout_seconds: int = Field(default=10, ge=1, le=300)
    request_timeout_seconds: float = Field(default=15, gt=0, le=600)
    max_concurrent_requests: int = Field(default=16, ge=1, le=200)
    max_queued_requests: int = Field(default=32, ge=0, le=500)
    queue_timeout_seconds: float = Field(default=1, gt=0, le=60)
    retry_max_attempts: int = Field(default=3, ge=1, le=6)
    retry_base_delay_seconds: float = Field(default=0.1, ge=0, le=5)
    retry_max_delay_seconds: float = Field(default=2, ge=0, le=30)
    retry_budget_capacity: int = Field(default=20, ge=0, le=1000)
    retry_budget_refill_per_second: float = Field(default=2, ge=0, le=100)
    circuit_failure_threshold: int = Field(default=5, ge=1, le=100)
    circuit_reset_seconds: float = Field(default=10, gt=0, le=600)
    cache_backend: Literal["disabled", "memory", "redis"] = "disabled"
    cache_ttl_seconds: int = Field(default=15, ge=1, le=3600)
    cache_max_entries: int = Field(default=1000, ge=1, le=100000)
    redis_host: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
    redis_port: int = Field(default=6380, ge=1, le=65535)
    redis_username: str | None = None
    redis_timeout_seconds: float = Field(default=1, gt=0, le=10)
    allow_unsafe_tests: bool = False
    poc_mode: bool = True
    readiness_mode: Literal["database", "process"] = "database"
    internal_api_token: SecretStr | None = None
    internal_allowed_networks: tuple[str, ...] = (
        "127.0.0.0/8",
        "::1/128",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
    )
    applicationinsights_connection_string: SecretStr | None = None
    database_target_role: Literal["primary", "secondary", "unknown"] = "primary"
    database_profile: str = Field(default="local", pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    compute_tier: Literal["local", "provisioned", "serverless"] = "local"
    vcore_configuration: str = Field(default="TBD", pattern=r"^[A-Za-z0-9_.-]{1,32}$")
    deployment_region: str = Field(default="local", pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    application_version: str = Field(default="0.2.0", pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    schema_version: str = Field(default="0002", pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    dataset_version: str = Field(default="synthetic-v1", pattern=r"^[A-Za-z0-9_.-]{1,64}$")

    @field_validator("cors_allow_origins")
    @classmethod
    def validate_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                "*" in origin
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS origins must be explicit HTTP(S) origins without paths.")
            try:
                _ = parsed.port
            except ValueError:
                raise ValueError("CORS origin has an invalid port.") from None
        return tuple(dict.fromkeys(origins))


def assert_local_memory_allowed(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> None:
    environment = os.environ if environ is None else environ
    if settings.app_environment not in {"local", "test"} or any(
        environment.get(marker) for marker in CLOUD_MARKERS
    ):
        raise ValueError(
            "In-memory storage is local/test only. "
            "Configure a durable repository before deployment."
        )

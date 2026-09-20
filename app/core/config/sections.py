from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class ConfigSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeSettings(ConfigSection):
    app_env: Literal["local", "dev", "test", "prd"] = "local"

    @property
    def is_release_env(self) -> bool:
        return self.app_env in {"test", "prd"}


class ServiceSettings(ConfigSection):
    name: str = "fastapi-lite"
    title: str = "FastAPI Lite"
    api_prefix: str = "/v1"

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("SERVICE__API_PREFIX must start with /")
        if len(value) > 1 and value.endswith("/"):
            raise ValueError("SERVICE__API_PREFIX must not end with /")
        return value


class SecuritySettings(ConfigSection):
    service_api_key: SecretStr = Field(default=SecretStr("dev-service-key"), repr=False)
    disable_auth: bool = False
    allowed_origins: str = "http://localhost:3000"

    @property
    def service_api_key_value(self) -> str:
        return self.service_api_key.get_secret_value()

    @property
    def allowed_origin_list(self) -> tuple[str, ...]:
        values = tuple(item.strip() for item in self.allowed_origins.split(",") if item.strip())
        if not values:
            raise ValueError("SECURITY__ALLOWED_ORIGINS must contain at least one origin")
        return values


class DatabaseSettings(ConfigSection):
    url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:25432/fastapi_lite"
    ssl: bool = False
    pool_size: int = 5
    max_overflow: int = 10

    @model_validator(mode="after")
    def validate_database(self) -> "DatabaseSettings":
        if self.pool_size <= 0:
            raise ValueError("DATABASE__POOL_SIZE must be greater than 0")
        if self.max_overflow < 0:
            raise ValueError("DATABASE__MAX_OVERFLOW must be greater than or equal to 0")
        return self

    @property
    def sync_url(self) -> str:
        if self.url.startswith("postgresql+asyncpg://"):
            return self.url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
        return self.url


class RedisSettings(ConfigSection):
    enabled: bool = False
    url: str = "redis://127.0.0.1:26379/0"


class StorageSettings(ConfigSection):
    backend: Literal["disabled", "local", "s3_compatible"] = "disabled"
    local_path: str = "storage/objects"
    endpoint: str = ""
    bucket: str = ""
    region: str = ""
    access_key_id: str = ""
    access_key_secret: SecretStr = Field(default=SecretStr(""), repr=False)

    @model_validator(mode="after")
    def validate_storage(self) -> "StorageSettings":
        if self.backend == "local" and not self.local_path.strip():
            raise ValueError("STORAGE__LOCAL_PATH is required when STORAGE__BACKEND=local")
        if self.backend == "s3_compatible":
            required = {
                "STORAGE__ENDPOINT": self.endpoint,
                "STORAGE__BUCKET": self.bucket,
                "STORAGE__REGION": self.region,
                "STORAGE__ACCESS_KEY_ID": self.access_key_id,
                "STORAGE__ACCESS_KEY_SECRET": self.access_key_secret.get_secret_value(),
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"STORAGE__BACKEND=s3_compatible requires: {', '.join(missing)}")
        return self


class HttpClientSettings(ConfigSection):
    timeout_seconds: float = 5

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("HTTP_CLIENT__TIMEOUT_SECONDS must be greater than 0")
        return value


class ObservabilitySettings(ConfigSection):
    log_level: str = "INFO"
    access_log_enabled: bool = True
    health_access_log: bool = False

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("OBSERVABILITY__LOG_LEVEL must be a valid Python logging level")
        return normalized


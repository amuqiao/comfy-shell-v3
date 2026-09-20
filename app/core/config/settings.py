from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.env_manifest import ENV_KEY_MANIFEST
from app.core.config.sections import (
    DatabaseSettings,
    HttpClientSettings,
    ObservabilitySettings,
    RedisSettings,
    RuntimeSettings,
    SecuritySettings,
    ServiceSettings,
    StorageSettings,
)
from app.core.config.validation import validate_release_invariants

ROOT_DIR = Path(__file__).resolve().parents[3]
APP_ENV_PREFIXES = tuple(
    sorted({key.split("__", 1)[0] + "__" for key in ENV_KEY_MANIFEST.application_keys if "__" in key})
)


def _env_file_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def validate_app_env_key_drift() -> None:
    allowed = ENV_KEY_MANIFEST.application_keys | ENV_KEY_MANIFEST.launcher_keys
    keys = set(os.environ) | _env_file_keys(ROOT_DIR / ".env")
    issues = []
    for key in sorted(keys):
        if key in ENV_KEY_MANIFEST.forbidden_keys:
            issues.append(f"forbidden config key: {key}")
        elif key.startswith(APP_ENV_PREFIXES) and key not in allowed:
            issues.append(f"unknown application config key: {key}")
    if issues:
        raise ValueError("; ".join(issues))


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_nested_delimiter="__",
        extra="ignore",
        frozen=True,
    )

    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    service: ServiceSettings = Field(default_factory=ServiceSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    http_client: HttpClientSettings = Field(default_factory=HttpClientSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    @model_validator(mode="after")
    def validate_invariants(self) -> "AppSettings":
        self.security.allowed_origin_list
        validate_release_invariants(
            runtime=self.runtime,
            security=self.security,
            storage=self.storage,
            database_url=self.database.url,
            redis_url=self.redis.url,
        )
        return self


@lru_cache
def get_settings() -> AppSettings:
    validate_app_env_key_drift()
    return AppSettings()

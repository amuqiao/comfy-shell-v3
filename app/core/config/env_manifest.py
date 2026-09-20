from __future__ import annotations

from dataclasses import dataclass


APPLICATION_ENV_KEYS = frozenset(
    {
        "RUNTIME__APP_ENV",
        "SERVICE__NAME",
        "SERVICE__TITLE",
        "SERVICE__API_PREFIX",
        "SECURITY__SERVICE_API_KEY",
        "SECURITY__DISABLE_AUTH",
        "SECURITY__ALLOWED_ORIGINS",
        "DATABASE__URL",
        "DATABASE__SSL",
        "DATABASE__POOL_SIZE",
        "DATABASE__MAX_OVERFLOW",
        "REDIS__ENABLED",
        "REDIS__URL",
        "STORAGE__BACKEND",
        "STORAGE__LOCAL_PATH",
        "STORAGE__ENDPOINT",
        "STORAGE__BUCKET",
        "STORAGE__REGION",
        "STORAGE__ACCESS_KEY_ID",
        "STORAGE__ACCESS_KEY_SECRET",
        "HTTP_CLIENT__TIMEOUT_SECONDS",
        "OBSERVABILITY__LOG_LEVEL",
        "OBSERVABILITY__ACCESS_LOG_ENABLED",
        "OBSERVABILITY__HEALTH_ACCESS_LOG",
    }
)

LAUNCHER_ENV_KEYS = frozenset(
    {
        "API_HOST",
        "API_PORT",
        "API_HOST_PORT",
        "COMPOSE_PROJECT_NAME",
        "POSTGRES_DB",
        "POSTGRES_HOST_PORT",
        "REDIS_HOST_PORT",
    }
)

DERIVED_ENV_KEYS = frozenset({"DATABASE__SYNC_URL"})
DEPRECATED_ENV_KEYS = frozenset({"SERVICE__ENV", "SERVICE__API_KEY", "LOG_LEVEL"})


@dataclass(frozen=True)
class EnvKeyManifest:
    application_keys: frozenset[str]
    launcher_keys: frozenset[str]
    derived_keys: frozenset[str]
    deprecated_keys: frozenset[str]

    @property
    def example_keys(self) -> frozenset[str]:
        return self.application_keys | self.launcher_keys

    @property
    def forbidden_keys(self) -> frozenset[str]:
        return self.derived_keys | self.deprecated_keys


ENV_KEY_MANIFEST = EnvKeyManifest(
    application_keys=APPLICATION_ENV_KEYS,
    launcher_keys=LAUNCHER_ENV_KEYS,
    derived_keys=DERIVED_ENV_KEYS,
    deprecated_keys=DEPRECATED_ENV_KEYS,
)


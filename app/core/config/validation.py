from urllib.parse import urlparse

from app.core.config.sections import RuntimeSettings, SecuritySettings, StorageSettings

PLACEHOLDER_SECRET_VALUES = frozenset({"", "<replace-me>", "<替换为随机 token>", "dev-service-key"})


def looks_like_placeholder_secret(value: str) -> bool:
    stripped = value.strip()
    return stripped in PLACEHOLDER_SECRET_VALUES or (stripped.startswith("<") and stripped.endswith(">"))


def looks_like_loopback_url(value: str) -> bool:
    parsed = urlparse(value)
    host = parsed.hostname or ""
    return host in {"127.0.0.1", "localhost", "::1"}


def validate_release_invariants(
    *,
    runtime: RuntimeSettings,
    security: SecuritySettings,
    storage: StorageSettings,
    database_url: str,
    redis_url: str,
) -> None:
    if runtime.is_release_env:
        if security.disable_auth:
            raise ValueError("release RUNTIME__APP_ENV must not set SECURITY__DISABLE_AUTH=true")
        if storage.backend == "local":
            raise ValueError("release RUNTIME__APP_ENV must not use STORAGE__BACKEND=local")
        if looks_like_placeholder_secret(security.service_api_key_value) or len(security.service_api_key_value) < 16:
            raise ValueError("release RUNTIME__APP_ENV requires a non-placeholder SECURITY__SERVICE_API_KEY")

    if security.disable_auth:
        if not looks_like_loopback_url(database_url):
            raise ValueError("DATABASE__URL must point to loopback when SECURITY__DISABLE_AUTH=true")
        if not looks_like_loopback_url(redis_url):
            raise ValueError("REDIS__URL must point to loopback when SECURITY__DISABLE_AUTH=true")


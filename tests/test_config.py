from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import AppSettings
from app.core.config.settings import validate_app_env_key_drift
from scripts.verify.env_config_check import check_env_file, check_example_alignment


def test_settings_are_sectioned_and_load_defaults():
    settings = AppSettings()

    assert settings.runtime.app_env == "local"
    assert settings.service.api_prefix == "/v1"
    assert settings.storage.backend == "disabled"


def test_release_rejects_placeholder_secret():
    with pytest.raises(ValidationError, match="SECURITY__SERVICE_API_KEY"):
        AppSettings(runtime={"app_env": "prd"}, storage={"backend": "disabled"})


def test_release_rejects_local_storage():
    with pytest.raises(ValidationError, match="STORAGE__BACKEND=local"):
        AppSettings(
            runtime={"app_env": "prd"},
            security={"service_api_key": "prd-secret-token-123456"},
            storage={"backend": "local"},
        )


def test_env_example_matches_manifest():
    issues = check_example_alignment(Path(".env.example"))

    assert issues == []


def test_env_file_rejects_deprecated_and_derived_keys(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SERVICE__ENV=local\nDATABASE__SYNC_URL=postgresql://x\n", encoding="utf-8")

    issues = check_env_file(env_file)

    assert any("deprecated config key: SERVICE__ENV" in issue for issue in issues)
    assert any("derived config key must not be set: DATABASE__SYNC_URL" in issue for issue in issues)


def test_runtime_env_rejects_unknown_application_key(monkeypatch):
    monkeypatch.setenv("DATABASE__URLL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:25432/app")

    with pytest.raises(ValueError, match="unknown application config key: DATABASE__URLL"):
        validate_app_env_key_drift()


def test_runtime_env_allows_launcher_keys(monkeypatch):
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "fastapi-lite-test")

    validate_app_env_key_drift()

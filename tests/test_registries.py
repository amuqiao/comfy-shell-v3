import pytest
from fastapi import FastAPI

from app.api.operations import operation_registry
from app.core.config import AppSettings
from app.core.error_registry import error_registry
from app.core.lifecycle import build_health_registry
from app.core.registry_checks import validate_operation_route_drift
from app.main import build_lifecycle_provider_registry, create_app
from scripts.verify.registry_check import API_CONTRACT_DOC, validate_api_contract_route_table


def test_error_registry_contains_internal_error():
    error_registry.validate()
    assert error_registry.get("INTERNAL_ERROR").http_status == 500


def test_operation_registry_contains_foundation_routes():
    operation_registry.validate()
    settings = AppSettings()
    paths = {item.full_path(settings.service.api_prefix) for item in operation_registry.all()}

    assert "/health" in paths
    assert "/ready" in paths
    assert "/v1/items" in paths
    assert all(item.response_schema for item in operation_registry.all())


def test_health_registry_contains_process_check():
    registry = build_health_registry()

    assert [item.name for item in registry.all()] == ["process"]


def test_operation_registry_matches_mounted_routes():
    validate_operation_route_drift(create_app())


def test_operation_registry_matches_configured_api_prefix():
    settings = AppSettings(
        service={"api_prefix": "/api"},
        security={"service_api_key": "test-service-key", "disable_auth": False},
        database={"url": "sqlite+aiosqlite:///:memory:"},
        storage={"backend": "disabled"},
        observability={"access_log_enabled": False},
    )

    validate_operation_route_drift(create_app(settings))


def test_operation_registry_drift_detects_unregistered_route():
    app = create_app()

    @app.get("/v1/unregistered", operation_id="unregistered")
    async def unregistered():
        return {"ok": True}

    with pytest.raises(RuntimeError, match="operation registry drift"):
        validate_operation_route_drift(app)


def test_operation_registry_drift_detects_status_mismatch():
    app = FastAPI()

    @app.post("/v1/items", operation_id="create_item", status_code=200)
    async def create_item():
        return {"ok": True}

    with pytest.raises(RuntimeError, match="operation registry drift"):
        validate_operation_route_drift(app)


def test_operation_registry_requires_openapi_contract_metadata():
    app = create_app()
    route = next(route for route in app.routes if getattr(route, "operation_id", None) == "create_item")
    route.response_model = None

    with pytest.raises(RuntimeError, match="operation contract drift"):
        validate_operation_route_drift(app)


def test_api_contract_route_table_matches_registry():
    validate_api_contract_route_table()


def test_api_contract_route_table_uses_default_documented_prefix(monkeypatch):
    monkeypatch.setenv("SERVICE__API_PREFIX", "/api")

    validate_api_contract_route_table()


def test_api_contract_route_table_detects_docs_drift(tmp_path):
    drifted = tmp_path / "api-contract.md"
    drifted.write_text(API_CONTRACT_DOC.read_text(encoding="utf-8").replace("POST /v1/items", "POST /v2/items"))

    with pytest.raises(RuntimeError, match="api contract route table drift"):
        validate_api_contract_route_table(drifted)


def test_default_lifecycle_provider_registry_contains_foundation_providers():
    registry = build_lifecycle_provider_registry()
    names = {provider.name for provider in registry.all()}

    assert names == {"postgres", "redis", "object_storage", "http_client"}

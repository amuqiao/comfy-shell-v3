import logging

from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.core.context import REQUEST_ID_HEADER, TRACE_ID_HEADER
from app.core.exceptions import AppError
from app.core.lifecycle import HealthCheck, HealthCheckRegistry, HealthCheckResult
from app.main import create_app


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def attach_log_recorder(app) -> ListHandler:
    handler = ListHandler()
    logging.getLogger().addHandler(handler)
    app.state.test_log_handler = handler
    return handler


def test_health_envelope_and_context_headers(app):
    with TestClient(app) as client:
        response = client.get("/health", headers={REQUEST_ID_HEADER: "req-test", TRACE_ID_HEADER: "trace-test"})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "req-test"
    assert response.headers[TRACE_ID_HEADER] == "trace-test"
    body = response.json()
    assert body["code"] == "OK"
    assert body["request_id"] == "req-test"
    assert body["trace_id"] == "trace-test"
    assert body["data"]["status"] == "ok"


def test_ready_uses_health_registry(sqlite_app):
    with TestClient(sqlite_app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "OK"
    assert body["data"]["status"] == "ok"
    check_names = {check["name"] for check in body["data"]["checks"]}
    assert {"process", "postgres", "redis", "object_storage", "http_client"}.issubset(check_names)


def test_ready_reports_postgres_connectivity_failure():
    settings = AppSettings(
        security={"service_api_key": "test-service-key", "disable_auth": False},
        database={"url": "postgresql+asyncpg://postgres:postgres@127.0.0.1:1/fastapi_lite"},
        storage={"backend": "disabled"},
        observability={"access_log_enabled": False},
    )
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE"
    postgres_check = next(check for check in body["details"]["checks"] if check["name"] == "postgres")
    assert postgres_check["status"] == "failed"


def test_ready_rejects_non_postgres_database_without_test_override(test_settings):
    app = create_app(test_settings)

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    postgres_check = next(check for check in body["details"]["checks"] if check["name"] == "postgres")
    assert postgres_check["status"] == "failed"
    assert postgres_check["details"]["reason"] == "non_postgres_database_url"


def test_ready_returns_503_when_required_check_fails(app):
    async def fail_check():
        return HealthCheckResult(name="database", status="failed", details={"reason": "down"})

    registry = HealthCheckRegistry()
    registry.register(HealthCheck(name="database", check=fail_check, required=True))
    registry.freeze()
    with TestClient(app) as client:
        client.app.state.health_checks = registry
        response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE"
    assert body["details"]["status"] == "failed"


def test_ready_returns_degraded_200_when_optional_check_fails(app):
    async def fail_check():
        return HealthCheckResult(name="cache", status="failed", details={"reason": "down"})

    registry = HealthCheckRegistry()
    registry.register(HealthCheck(name="cache", check=fail_check, required=False))
    registry.freeze()
    with TestClient(app) as client:
        client.app.state.health_checks = registry
        response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "OK"
    assert body["data"]["status"] == "degraded"


def test_invalid_request_id_returns_error_envelope(app):
    with TestClient(app) as client:
        response = client.get("/health", headers={REQUEST_ID_HEADER: "bad id with spaces"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "REQUEST_INVALID"
    assert body["details"]["header"] == REQUEST_ID_HEADER


def test_invalid_trace_id_returns_error_envelope(app):
    with TestClient(app) as client:
        response = client.get("/health", headers={TRACE_ID_HEADER: "bad trace with spaces"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "REQUEST_INVALID"
    assert body["details"]["header"] == TRACE_ID_HEADER


def test_app_error_returns_registered_error_envelope(app):
    router = APIRouter()

    @router.get("/_test/app-error")
    async def raise_app_error():
        raise AppError("FORBIDDEN")

    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/_test/app-error")

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_validation_error_returns_request_invalid(app):
    router = APIRouter()

    @router.get("/_test/validation")
    async def validation_route(count: int):
        return {"count": count}

    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/_test/validation", params={"count": "abc"})

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_unhandled_exception_returns_internal_error(test_settings):
    from app.main import create_app

    app = create_app(test_settings)
    router = APIRouter()

    @router.get("/_test/boom")
    async def boom():
        raise RuntimeError("boom")

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/boom")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"


def test_method_not_allowed_preserves_http_status(app):
    with TestClient(app) as client:
        response = client.post("/health")

    assert response.status_code == 405
    assert response.json()["code"] == "REQUEST_INVALID"


def test_openapi_exposes_route_contract(app):
    schema = app.openapi()

    create_item = schema["paths"]["/v1/items"]["post"]
    assert create_item["operationId"] == "create_item"
    assert create_item["security"]
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    assert create_item["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/ItemCreateRequest")
    assert "201" in create_item["responses"]
    assert "401" in create_item["responses"]
    assert "409" in create_item["responses"]
    assert "422" in create_item["responses"]
    assert create_item["responses"]["409"]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorEnvelope")

    health = schema["paths"]["/health"]["get"]
    assert "security" not in health


def test_access_log_exposes_stable_fields(test_settings):
    settings = AppSettings(
        security={"service_api_key": "test-service-key", "disable_auth": False},
        database={"url": "sqlite+aiosqlite:///:memory:"},
        storage={"backend": "disabled"},
        observability={"access_log_enabled": True, "health_access_log": True},
    )
    app = create_app(settings)
    handler = attach_log_recorder(app)

    with TestClient(app) as client:
        response = client.get("/health", headers={REQUEST_ID_HEADER: "req-log", TRACE_ID_HEADER: "trace-log"})

    assert response.status_code == 200
    record = next(item for item in handler.records if item.getMessage() == "request_completed")
    assert record.request_id == "req-log"
    assert record.trace_id == "trace-log"
    assert record.method == "GET"
    assert record.path == "/health"
    assert record.operation_id == "health"
    assert record.status == 200
    assert isinstance(record.duration_ms, int)


def test_invalid_header_access_log_exposes_stable_fields(test_settings):
    settings = AppSettings(
        security={"service_api_key": "test-service-key", "disable_auth": False},
        database={"url": "sqlite+aiosqlite:///:memory:"},
        storage={"backend": "disabled"},
        observability={"access_log_enabled": True},
    )
    app = create_app(settings)
    handler = attach_log_recorder(app)
    router = APIRouter()

    @router.get("/_test/context", operation_id="context")
    async def context_route():
        return {"ok": True}

    app.include_router(router)

    with TestClient(app) as client:
        response = client.get("/_test/context", headers={REQUEST_ID_HEADER: "bad id with spaces"})

    assert response.status_code == 422
    record = next(item for item in handler.records if item.getMessage() == "request_completed")
    assert record.method == "GET"
    assert record.path == "/_test/context"
    assert record.operation_id == "-"
    assert record.status == 422
    assert isinstance(record.duration_ms, int)


def test_invalid_health_header_respects_health_access_log(test_settings):
    settings = AppSettings(
        security={"service_api_key": "test-service-key", "disable_auth": False},
        database={"url": "sqlite+aiosqlite:///:memory:"},
        storage={"backend": "disabled"},
        observability={"access_log_enabled": True, "health_access_log": False},
    )
    app = create_app(settings)
    handler = attach_log_recorder(app)

    with TestClient(app) as client:
        response = client.get("/health", headers={REQUEST_ID_HEADER: "bad id with spaces"})

    assert response.status_code == 422
    assert not [item for item in handler.records if item.getMessage() == "request_completed"]


def test_app_error_log_exposes_stable_fields(test_settings):
    app = create_app(test_settings)
    handler = attach_log_recorder(app)
    router = APIRouter()

    @router.get("/_test/logged-app-error", operation_id="logged_app_error")
    async def raise_app_error():
        raise AppError("FORBIDDEN")

    app.include_router(router)
    with TestClient(app) as client:
        response = client.get(
            "/_test/logged-app-error",
            headers={REQUEST_ID_HEADER: "req-error", TRACE_ID_HEADER: "trace-error"},
        )

    assert response.status_code == 403
    record = next(item for item in handler.records if item.getMessage() == "app_error")
    assert record.request_id == "req-error"
    assert record.trace_id == "trace-error"
    assert record.method == "GET"
    assert record.path == "/_test/logged-app-error"
    assert record.operation_id == "logged_app_error"
    assert record.status == 403
    assert record.error_code == "FORBIDDEN"

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes.items import router as items_router
from app.api.routes.health import router as health_router
from app.core.config import AppSettings, get_settings
from app.core.context import get_request_id, get_trace_id
from app.core.exceptions import AppError
from app.core.lifecycle import LifecycleProviderRegistry, build_health_registry
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware, operation_id_for_request
from app.integrations.http_client import HttpClientProvider
from app.integrations.postgres import PostgresProvider
from app.integrations.redis import RedisProvider
from app.integrations.storage import ObjectStorageProvider
from app.schemas.envelope import error_envelope

logger = logging.getLogger(__name__)


def build_lifecycle_provider_registry() -> LifecycleProviderRegistry:
    provider_registry = LifecycleProviderRegistry()
    provider_registry.register(PostgresProvider())
    provider_registry.register(RedisProvider())
    provider_registry.register(ObjectStorageProvider())
    provider_registry.register(HttpClientProvider())
    provider_registry.validate()
    return provider_registry


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = application.state.settings
    health_registry = build_health_registry()
    provider_registry = build_lifecycle_provider_registry()
    application.state.lifecycle_providers = provider_registry
    application.state.health_checks = health_registry
    await provider_registry.startup(application, settings, health_registry)
    health_registry.validate()
    health_registry.freeze()
    try:
        yield
    finally:
        await provider_registry.shutdown(application)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", get_request_id())


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", get_trace_id())


def _log_extra(request: Request, *, status: int, error_code: str) -> dict[str, object]:
    return {
        "method": request.method,
        "path": request.url.path,
        "operation_id": operation_id_for_request(request),
        "status": status,
        "duration_ms": "-",
        "error_code": error_code,
    }


def install_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        status_code, body = error_envelope(
            exc.code,
            request_id=_request_id(request),
            trace_id=_trace_id(request),
            details=exc.details,
        )
        logger.warning("app_error", extra=_log_extra(request, status=status_code, error_code=exc.code))
        return JSONResponse(status_code=status_code, content=jsonable_encoder(body))

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "loc": list(error.get("loc", ())),
                "type": str(error.get("type", "")),
                "msg": str(error.get("msg", "")),
            }
            for error in exc.errors()
        ]
        status_code, body = error_envelope(
            "REQUEST_INVALID",
            request_id=_request_id(request),
            trace_id=_trace_id(request),
            details={"errors": errors},
        )
        return JSONResponse(status_code=status_code, content=jsonable_encoder(body))

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "RESOURCE_NOT_FOUND" if exc.status_code == 404 else "REQUEST_INVALID"
        status_code, body = error_envelope(
            code,
            request_id=_request_id(request),
            trace_id=_trace_id(request),
            http_status=exc.status_code,
            details={"status_code": exc.status_code},
        )
        return JSONResponse(status_code=status_code, content=jsonable_encoder(body), headers=exc.headers)

    @application.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        status_code, body = error_envelope(
            "INTERNAL_ERROR",
            request_id=_request_id(request),
            trace_id=_trace_id(request),
        )
        logger.exception(
            "unhandled_exception",
            extra=_log_extra(request, status=status_code, error_code="INTERNAL_ERROR"),
        )
        return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


def install_openapi(application: FastAPI) -> None:
    def is_error_envelope_response(response: object) -> bool:
        if not isinstance(response, dict):
            return False
        schema = response.get("content", {}).get("application/json", {}).get("schema", {})
        return isinstance(schema, dict) and str(schema.get("$ref", "")).endswith("/ErrorEnvelope")

    def custom_openapi():
        if application.openapi_schema:
            return application.openapi_schema
        schema = get_openapi(title=application.title, version=application.version, routes=application.routes)
        for path_item in schema.get("paths", {}).values():
            for operation in path_item.values():
                if isinstance(operation, dict):
                    response_422 = operation.get("responses", {}).get("422")
                    if not is_error_envelope_response(response_422):
                        operation.get("responses", {}).pop("422", None)
        application.openapi_schema = schema
        return application.openapi_schema

    application.openapi = custom_openapi


def create_app(settings: AppSettings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings)
    application = FastAPI(title=app_settings.service.title, version="0.1.0", lifespan=lifespan)
    application.state.settings = app_settings
    application.add_middleware(RequestContextMiddleware, settings=app_settings)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.security.allowed_origin_list),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(items_router, prefix=app_settings.service.api_prefix)
    install_openapi(application)
    return application


app = create_app()

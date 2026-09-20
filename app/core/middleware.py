import logging
import re
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.context import REQUEST_ID_HEADER, TRACE_ID_HEADER, set_request_context
from app.core.config import AppSettings

REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9._:-]{1,128}$")
HEALTH_PATHS = {"/health", "/ready"}
logger = logging.getLogger(__name__)


def new_context_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def operation_id_for_request(request: Request) -> str:
    route = request.scope.get("route")
    return str(getattr(route, "operation_id", "") or "-")


def log_request_completed(
    request: Request,
    *,
    status_code: int,
    duration_ms: int,
) -> None:
    logger.info(
        "request_completed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "operation_id": operation_id_for_request(request),
            "status": status_code,
            "duration_ms": duration_ms,
        },
    )


def should_log_access(settings: AppSettings, path: str) -> bool:
    return settings.observability.access_log_enabled and (
        settings.observability.health_access_log or path not in HEALTH_PATHS
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, settings: AppSettings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):
        raw_request_id = request.headers.get(REQUEST_ID_HEADER)
        raw_trace_id = request.headers.get(TRACE_ID_HEADER)
        trace_id = raw_trace_id or new_context_id("trace")
        request_id = raw_request_id or new_context_id("req")
        set_request_context(request_id=request_id, trace_id=trace_id)
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        started = time.monotonic()

        invalid_header = None
        if raw_request_id is not None and not REQUEST_ID_RE.fullmatch(raw_request_id):
            invalid_header = REQUEST_ID_HEADER
            request_id = new_context_id("req")
        elif raw_trace_id is not None and not REQUEST_ID_RE.fullmatch(raw_trace_id):
            invalid_header = TRACE_ID_HEADER
            trace_id = new_context_id("trace")

        if invalid_header is not None:
            set_request_context(request_id=request_id, trace_id=trace_id)
            request.state.request_id = request_id
            request.state.trace_id = trace_id
            from fastapi.encoders import jsonable_encoder
            from fastapi.responses import JSONResponse

            from app.schemas.envelope import error_envelope

            status_code, body = error_envelope(
                "REQUEST_INVALID",
                request_id=request_id,
                trace_id=trace_id,
                details={"header": invalid_header},
            )
            if should_log_access(self._settings, request.url.path):
                duration_ms = int((time.monotonic() - started) * 1000)
                log_request_completed(request, status_code=status_code, duration_ms=duration_ms)
            return JSONResponse(
                status_code=status_code,
                content=jsonable_encoder(body),
                headers={REQUEST_ID_HEADER: request_id, TRACE_ID_HEADER: trace_id},
            )

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[TRACE_ID_HEADER] = trace_id
        if should_log_access(self._settings, request.url.path):
            duration_ms = int((time.monotonic() - started) * 1000)
            log_request_completed(request, status_code=response.status_code, duration_ms=duration_ms)
        return response

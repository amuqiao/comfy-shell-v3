from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from app.core.error_registry import error_registry
from app.schemas.common import StrictBaseModel

TData = TypeVar("TData")


class SuccessEnvelope(StrictBaseModel, Generic[TData]):
    request_id: str
    trace_id: str
    server_time: str
    code: str = "OK"
    data: TData


class ErrorEnvelope(StrictBaseModel):
    request_id: str
    trace_id: str
    server_time: str
    code: str
    message: str
    retryable: bool
    details: dict[str, Any]


def server_time_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def success_envelope(data: TData, *, request_id: str, trace_id: str) -> SuccessEnvelope[TData]:
    return SuccessEnvelope[TData](
        request_id=request_id,
        trace_id=trace_id,
        server_time=server_time_now(),
        data=data,
    )


def error_envelope(
    code: str,
    *,
    request_id: str,
    trace_id: str,
    http_status: int | None = None,
    details: dict[str, Any] | None = None,
) -> tuple[int, ErrorEnvelope]:
    spec = error_registry.get(code)
    return http_status or spec.http_status, ErrorEnvelope(
        request_id=request_id,
        trace_id=trace_id,
        server_time=server_time_now(),
        code=spec.code,
        message=spec.message,
        retryable=spec.retryable,
        details=details or {},
    )

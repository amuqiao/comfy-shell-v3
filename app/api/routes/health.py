from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api.operations import operation_responses
from app.core.context import get_request_id, get_trace_id
from app.core.lifecycle import run_health_checks
from app.schemas.envelope import SuccessEnvelope, error_envelope, success_envelope

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    operation_id="health",
    response_model=SuccessEnvelope[dict[str, str]],
    responses=operation_responses("health"),
)
async def health() -> SuccessEnvelope[dict[str, str]]:
    return success_envelope(
        {"status": "ok"},
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.get(
    "/ready",
    operation_id="ready",
    response_model=SuccessEnvelope[dict[str, object]],
    responses=operation_responses("ready"),
)
async def ready(request: Request) -> object:
    result = await run_health_checks(request.app.state.health_checks)
    if result["status"] == "failed":
        status_code, body = error_envelope(
            "DEPENDENCY_UNAVAILABLE",
            request_id=get_request_id(),
            trace_id=get_trace_id(),
            details=result,
        )
        return JSONResponse(status_code=status_code, content=jsonable_encoder(body))
    return success_envelope(
        result,
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )

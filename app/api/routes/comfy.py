from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.operations import operation_responses
from app.comfy import models, process, versions
from app.comfy.workspace import init_workspace
from app.core.context import get_request_id, get_trace_id
from app.core.security import Principal, get_current_principal
from app.schemas.comfy import (
    ComfyDictResponse,
    ComfyListResponse,
    ComfyLogResponse,
    ComfyModelDownloadRequest,
    ComfyVersionFetchRequest,
    ComfyVersionUseRequest,
)
from app.schemas.envelope import SuccessEnvelope, success_envelope

router = APIRouter(tags=["comfy"])


def settings_from_request(request: Request):
    return request.app.state.settings


@router.post(
    "/comfy/workspace/init",
    operation_id="comfy_workspace_init",
    response_model=SuccessEnvelope[ComfyDictResponse],
    responses=operation_responses("comfy_workspace_init"),
)
def workspace_init(
    request: Request,
    _principal: Annotated[Principal, Depends(get_current_principal)],
) -> SuccessEnvelope[ComfyDictResponse]:
    paths = init_workspace(settings_from_request(request))
    return success_envelope(ComfyDictResponse(data={"workspace": str(paths.root)}), request_id=get_request_id(), trace_id=get_trace_id())


@router.get(
    "/comfy/versions",
    operation_id="comfy_versions_list",
    response_model=SuccessEnvelope[ComfyListResponse],
    responses=operation_responses("comfy_versions_list"),
)
def list_versions(
    request: Request,
    _principal: Annotated[Principal, Depends(get_current_principal)],
) -> SuccessEnvelope[ComfyListResponse]:
    return success_envelope(
        ComfyListResponse(items=versions.list_versions(settings_from_request(request))),
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.post(
    "/comfy/versions/fetch",
    operation_id="comfy_versions_fetch",
    response_model=SuccessEnvelope[ComfyDictResponse],
    responses=operation_responses("comfy_versions_fetch"),
)
def fetch_version(
    request: Request,
    data: ComfyVersionFetchRequest,
    _principal: Annotated[Principal, Depends(get_current_principal)],
) -> SuccessEnvelope[ComfyDictResponse]:
    return success_envelope(
        ComfyDictResponse(data=versions.fetch_version(settings_from_request(request), data.ref)),
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.post(
    "/comfy/versions/use",
    operation_id="comfy_versions_use",
    response_model=SuccessEnvelope[ComfyDictResponse],
    responses=operation_responses("comfy_versions_use"),
)
def use_version(
    request: Request,
    data: ComfyVersionUseRequest,
    _principal: Annotated[Principal, Depends(get_current_principal)],
) -> SuccessEnvelope[ComfyDictResponse]:
    return success_envelope(
        ComfyDictResponse(data=versions.use_version(settings_from_request(request), data.name)),
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.get(
    "/comfy/versions/current",
    operation_id="comfy_versions_current",
    response_model=SuccessEnvelope[dict[str, Any] | None],
    responses=operation_responses("comfy_versions_current"),
)
def current_version(
    request: Request,
    _principal: Annotated[Principal, Depends(get_current_principal)],
) -> SuccessEnvelope[dict[str, Any] | None]:
    return success_envelope(
        versions.current_version(settings_from_request(request)),
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.get(
    "/comfy/models",
    operation_id="comfy_models_list",
    response_model=SuccessEnvelope[ComfyListResponse],
    responses=operation_responses("comfy_models_list"),
)
def list_models(
    request: Request,
    _principal: Annotated[Principal, Depends(get_current_principal)],
) -> SuccessEnvelope[ComfyListResponse]:
    return success_envelope(
        ComfyListResponse(items=models.list_models(settings_from_request(request))),
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.post(
    "/comfy/models/link",
    operation_id="comfy_models_link",
    response_model=SuccessEnvelope[ComfyDictResponse],
    responses=operation_responses("comfy_models_link"),
)
def link_models(
    request: Request,
    _principal: Annotated[Principal, Depends(get_current_principal)],
) -> SuccessEnvelope[ComfyDictResponse]:
    return success_envelope(
        ComfyDictResponse(data=models.link_models(settings_from_request(request))),
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.post(
    "/comfy/models/download",
    operation_id="comfy_models_download",
    response_model=SuccessEnvelope[ComfyDictResponse],
    responses=operation_responses("comfy_models_download"),
)
def download_model(
    request: Request,
    data: ComfyModelDownloadRequest,
    _principal: Annotated[Principal, Depends(get_current_principal)],
) -> SuccessEnvelope[ComfyDictResponse]:
    return success_envelope(
        ComfyDictResponse(
            data=models.hf_download(settings_from_request(request), data.repo_id, data.filename, data.target)
        ),
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.post(
    "/comfy/service/start",
    operation_id="comfy_service_start",
    response_model=SuccessEnvelope[ComfyDictResponse],
    responses=operation_responses("comfy_service_start"),
)
def start_service(
    request: Request,
    _principal: Annotated[Principal, Depends(get_current_principal)],
) -> SuccessEnvelope[ComfyDictResponse]:
    return success_envelope(
        ComfyDictResponse(data=process.start(settings_from_request(request))),
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.post(
    "/comfy/service/stop",
    operation_id="comfy_service_stop",
    response_model=SuccessEnvelope[ComfyDictResponse],
    responses=operation_responses("comfy_service_stop"),
)
def stop_service(
    request: Request,
    _principal: Annotated[Principal, Depends(get_current_principal)],
) -> SuccessEnvelope[ComfyDictResponse]:
    return success_envelope(
        ComfyDictResponse(data=process.stop(settings_from_request(request))),
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.get(
    "/comfy/service/status",
    operation_id="comfy_service_status",
    response_model=SuccessEnvelope[ComfyDictResponse],
    responses=operation_responses("comfy_service_status"),
)
def service_status(
    request: Request,
    _principal: Annotated[Principal, Depends(get_current_principal)],
) -> SuccessEnvelope[ComfyDictResponse]:
    return success_envelope(
        ComfyDictResponse(data=process.status(settings_from_request(request))),
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.get(
    "/comfy/service/logs",
    operation_id="comfy_service_logs",
    response_model=SuccessEnvelope[ComfyLogResponse],
    responses=operation_responses("comfy_service_logs"),
)
def service_logs(
    request: Request,
    _principal: Annotated[Principal, Depends(get_current_principal)],
    lines: Annotated[int, Query(ge=1, le=1000)] = 80,
) -> SuccessEnvelope[ComfyLogResponse]:
    return success_envelope(
        ComfyLogResponse(text=process.tail_log(settings_from_request(request), lines=lines)),
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.operations import operation_responses
from app.core.context import get_request_id, get_trace_id
from app.db.unit_of_work import uow_factory_from_session_factory
from app.core.security import Principal, get_current_principal
from app.schemas.envelope import SuccessEnvelope, success_envelope
from app.schemas.item import (
    ItemCreateRequest,
    ItemDeleteRequest,
    ItemListResponse,
    ItemResponse,
    ItemStatus,
    ItemUpdateRequest,
)
from app.services.item_service import ItemService

router = APIRouter(tags=["items"])


def get_item_service(request: Request) -> ItemService:
    session_factory = request.app.state.db_session_factory
    return ItemService(uow_factory_from_session_factory(session_factory))


@router.post(
    "/items",
    operation_id="create_item",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessEnvelope[ItemResponse],
    responses=operation_responses("create_item"),
)
async def create_item(
    data: ItemCreateRequest,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[ItemService, Depends(get_item_service)],
) -> SuccessEnvelope[ItemResponse]:
    item = await service.create_item(owner_id=principal.subject, data=data)
    return success_envelope(item, request_id=get_request_id(), trace_id=get_trace_id())


@router.get(
    "/items/{item_id}",
    operation_id="get_item",
    response_model=SuccessEnvelope[ItemResponse],
    responses=operation_responses("get_item"),
)
async def get_item(
    item_id: str,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[ItemService, Depends(get_item_service)],
) -> SuccessEnvelope[ItemResponse]:
    item = await service.get_item(owner_id=principal.subject, item_id=item_id)
    return success_envelope(item, request_id=get_request_id(), trace_id=get_trace_id())


@router.get(
    "/items",
    operation_id="list_items",
    response_model=SuccessEnvelope[ItemListResponse],
    responses=operation_responses("list_items"),
)
async def list_items(
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[ItemService, Depends(get_item_service)],
    item_status: Annotated[ItemStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> SuccessEnvelope[ItemListResponse]:
    page = await service.list_items(
        owner_id=principal.subject,
        status=item_status,
        limit=limit,
        cursor=cursor,
    )
    return success_envelope(page, request_id=get_request_id(), trace_id=get_trace_id())


@router.patch(
    "/items/{item_id}",
    operation_id="update_item",
    response_model=SuccessEnvelope[ItemResponse],
    responses=operation_responses("update_item"),
)
async def update_item(
    item_id: str,
    data: ItemUpdateRequest,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[ItemService, Depends(get_item_service)],
) -> SuccessEnvelope[ItemResponse]:
    item = await service.update_item(owner_id=principal.subject, item_id=item_id, data=data)
    return success_envelope(item, request_id=get_request_id(), trace_id=get_trace_id())


@router.delete(
    "/items/{item_id}",
    operation_id="delete_item",
    response_model=SuccessEnvelope[ItemResponse],
    responses=operation_responses("delete_item"),
)
async def delete_item(
    item_id: str,
    data: ItemDeleteRequest,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[ItemService, Depends(get_item_service)],
) -> SuccessEnvelope[ItemResponse]:
    item = await service.delete_item(
        owner_id=principal.subject,
        item_id=item_id,
        data=data,
        deleted_by=principal.subject,
    )
    return success_envelope(item, request_id=get_request_id(), trace_id=get_trace_id())

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AppError
from app.db.unit_of_work import UowFactory
from app.models.item import Item
from app.schemas.item import ItemCreateRequest, ItemDeleteRequest, ItemListResponse, ItemResponse, ItemStatus, ItemUpdateRequest

MAX_LIST_LIMIT = 100


def map_integrity_error(exc: IntegrityError) -> AppError:
    text = str(exc.orig)
    if "uq_items_owner_name_active" in text or "items.owner_id, items.name" in text:
        return AppError("ITEM_NAME_CONFLICT")
    return AppError("RESOURCE_CONFLICT")


def item_to_response(item: Item) -> ItemResponse:
    return ItemResponse(
        id=item.id,
        owner_id=item.owner_id,
        name=item.name,
        description=item.description,
        status=item.status,  # type: ignore[arg-type]
        version=item.version,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
    )


class ItemService:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def create_item(self, *, owner_id: str, data: ItemCreateRequest) -> ItemResponse:
        async with self._uow_factory() as uow:
            assert uow.items is not None
            existing = await uow.items.get_active_by_name(owner_id=owner_id, name=data.name)
            if existing is not None:
                raise AppError("ITEM_NAME_CONFLICT", details={"name": data.name})
            try:
                item = await uow.items.create(
                    owner_id=owner_id,
                    name=data.name,
                    description=data.description,
                    status=data.status,
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise map_integrity_error(exc) from exc
            return item_to_response(item)

    async def get_item(self, *, owner_id: str, item_id: str) -> ItemResponse:
        async with self._uow_factory() as uow:
            assert uow.items is not None
            item = await uow.items.get_active_by_id(owner_id=owner_id, item_id=item_id)
            if item is None:
                raise AppError("ITEM_NOT_FOUND", details={"item_id": item_id})
            return item_to_response(item)

    async def list_items(
        self,
        *,
        owner_id: str,
        status: ItemStatus | None,
        limit: int,
        cursor: str | None,
    ) -> ItemListResponse:
        if limit < 1 or limit > MAX_LIST_LIMIT:
            raise AppError("REQUEST_INVALID", details={"limit": f"must be between 1 and {MAX_LIST_LIMIT}"})
        async with self._uow_factory() as uow:
            assert uow.items is not None
            page = await uow.items.list_active(owner_id=owner_id, status=status, limit=limit, cursor=cursor)
            return ItemListResponse(
                items=[item_to_response(item) for item in page.items],
                next_cursor=page.next_cursor,
                limit=page.limit,
            )

    async def update_item(self, *, owner_id: str, item_id: str, data: ItemUpdateRequest) -> ItemResponse:
        async with self._uow_factory() as uow:
            assert uow.items is not None
            if data.name is not None:
                existing = await uow.items.get_active_by_name(owner_id=owner_id, name=data.name)
                if existing is not None and existing.id != item_id:
                    raise AppError("ITEM_NAME_CONFLICT", details={"name": data.name})
            try:
                result = await uow.items.update_cas(
                    owner_id=owner_id,
                    item_id=item_id,
                    expected_version=data.expected_version,
                    name=data.name,
                    description=data.description,
                    status=data.status,
                )
            except IntegrityError as exc:
                await uow.rollback()
                raise map_integrity_error(exc) from exc
            if result.status == "not_found":
                raise AppError("ITEM_NOT_FOUND", details={"item_id": item_id})
            if result.status == "version_conflict":
                raise AppError("ITEM_VERSION_CONFLICT", details={"current_version": result.current_version})
            assert result.item is not None
            await uow.commit()
            return item_to_response(result.item)

    async def delete_item(self, *, owner_id: str, item_id: str, data: ItemDeleteRequest, deleted_by: str) -> ItemResponse:
        async with self._uow_factory() as uow:
            assert uow.items is not None
            result = await uow.items.soft_delete_cas(
                owner_id=owner_id,
                item_id=item_id,
                expected_version=data.expected_version,
                deleted_by=deleted_by,
            )
            if result.status == "not_found":
                raise AppError("ITEM_NOT_FOUND", details={"item_id": item_id})
            if result.status == "version_conflict":
                raise AppError("ITEM_VERSION_CONFLICT", details={"current_version": result.current_version})
            assert result.item is not None
            await uow.commit()
            return item_to_response(result.item)

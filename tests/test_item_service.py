import pytest

from app.core.exceptions import AppError
from app.db.unit_of_work import uow_factory_from_session_factory
from app.schemas.item import ItemCreateRequest, ItemUpdateRequest
from app.services.item_service import ItemService


def service(sqlite_session_factory) -> ItemService:
    return ItemService(uow_factory_from_session_factory(sqlite_session_factory))


def test_item_service_requires_explicit_uow_factory():
    with pytest.raises(TypeError):
        ItemService()


@pytest.mark.asyncio
async def test_service_rolls_back_on_conflict(sqlite_session_factory):
    item_service = service(sqlite_session_factory)
    await item_service.create_item(owner_id="owner", data=ItemCreateRequest(name="same"))

    with pytest.raises(AppError, match="ITEM_NAME_CONFLICT"):
        await item_service.create_item(owner_id="owner", data=ItemCreateRequest(name="same"))

    page = await item_service.list_items(owner_id="owner", status=None, limit=10, cursor=None)
    assert len(page.items) == 1


@pytest.mark.asyncio
async def test_service_rejects_stale_update(sqlite_session_factory):
    item_service = service(sqlite_session_factory)
    item = await item_service.create_item(owner_id="owner", data=ItemCreateRequest(name="cas"))

    with pytest.raises(AppError) as exc:
        await item_service.update_item(
            owner_id="owner",
            item_id=item.id,
            data=ItemUpdateRequest(expected_version=2, description="stale"),
        )

    assert exc.value.code == "ITEM_VERSION_CONFLICT"

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.core.exceptions import AppError
from app.db.database import close_db_engine, get_session_factory, init_db_engine
from app.db.unit_of_work import uow_factory_from_session_factory
from app.models.item import Item
from app.schemas.item import ItemCreateRequest, ItemDeleteRequest, ItemUpdateRequest
from app.services.item_service import ItemService

pytestmark = [
    pytest.mark.postgres_integration,
    pytest.mark.skipif(
        os.environ.get("FASTAPI_LITE_POSTGRES_INTEGRATION") != "1",
        reason="set FASTAPI_LITE_POSTGRES_INTEGRATION=1 to run PostgreSQL integration tests",
    ),
]


@pytest_asyncio.fixture
async def postgres_uow_factory():
    init_db_engine()
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(delete(Item))
        await session.commit()
    try:
        yield uow_factory_from_session_factory(factory)
    finally:
        async with factory() as session:
            await session.execute(delete(Item))
            await session.commit()
        await close_db_engine()


@pytest.mark.asyncio
async def test_postgres_partial_unique_index_allows_reuse_after_soft_delete(postgres_uow_factory):
    service = ItemService(postgres_uow_factory)
    name = f"pg-{uuid.uuid4().hex}"
    created = await service.create_item(owner_id="pg", data=ItemCreateRequest(name=name))

    with pytest.raises(AppError) as conflict:
        await service.create_item(owner_id="pg", data=ItemCreateRequest(name=name))
    assert conflict.value.code == "ITEM_NAME_CONFLICT"

    await service.delete_item(
        owner_id="pg",
        item_id=created.id,
        data=ItemDeleteRequest(expected_version=created.version),
        deleted_by="pg",
    )
    recreated = await service.create_item(owner_id="pg", data=ItemCreateRequest(name=name))
    assert recreated.id != created.id


@pytest.mark.asyncio
async def test_postgres_atomic_cas_allows_one_winner(postgres_uow_factory):
    service = ItemService(postgres_uow_factory)
    created = await service.create_item(owner_id="pg", data=ItemCreateRequest(name=f"cas-{uuid.uuid4().hex}"))

    async def update(description: str):
        return await service.update_item(
            owner_id="pg",
            item_id=created.id,
            data=ItemUpdateRequest(expected_version=created.version, description=description),
        )

    results = await asyncio.gather(update("a"), update("b"), return_exceptions=True)
    successes = [item for item in results if not isinstance(item, Exception)]
    conflicts = [item for item in results if isinstance(item, AppError) and item.code == "ITEM_VERSION_CONFLICT"]

    assert len(successes) == 1
    assert len(conflicts) == 1

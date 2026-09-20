from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.pagination import Page, decode_cursor, encode_cursor
from app.models.item import Item
from app.repositories.base import MutationResult


class ItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        owner_id: str,
        name: str,
        description: str | None,
        status: str,
    ) -> Item:
        item = Item(owner_id=owner_id, name=name, description=description, status=status)
        self._session.add(item)
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def get_active_by_id(self, *, owner_id: str, item_id: str) -> Item | None:
        result = await self._session.execute(
            select(Item).where(Item.owner_id == owner_id, Item.id == item_id, Item.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_active_by_name(self, *, owner_id: str, name: str) -> Item | None:
        result = await self._session.execute(
            select(Item).where(Item.owner_id == owner_id, Item.name == name, Item.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_active(
        self,
        *,
        owner_id: str,
        status: str | None,
        limit: int,
        cursor: str | None,
    ) -> Page[Item]:
        filters = [Item.owner_id == owner_id, Item.deleted_at.is_(None)]
        if status is not None:
            filters.append(Item.status == status)
        if cursor:
            created_at, item_id = decode_cursor(cursor)
            filters.append(or_(Item.created_at < created_at, and_(Item.created_at == created_at, Item.id < item_id)))

        result = await self._session.execute(
            select(Item)
            .where(*filters)
            .order_by(Item.created_at.desc(), Item.id.desc())
            .limit(limit + 1)
        )
        rows = list(result.scalars().all())
        page_items = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page_items:
            last = page_items[-1]
            next_cursor = encode_cursor(created_at=last.created_at, item_id=last.id)
        return Page(items=page_items, next_cursor=next_cursor, limit=limit)

    async def update_cas(
        self,
        *,
        owner_id: str,
        item_id: str,
        expected_version: int,
        name: str | None,
        description: str | None,
        status: str | None,
    ) -> MutationResult[Item]:
        values: dict[str, object] = {Item.version: Item.version + 1}
        if name is not None:
            values[Item.name] = name
        if description is not None:
            values[Item.description] = description
        if status is not None:
            values[Item.status] = status
        result = await self._session.execute(
            update(Item)
            .where(
                Item.owner_id == owner_id,
                Item.id == item_id,
                Item.version == expected_version,
                Item.deleted_at.is_(None),
            )
            .values(values)
            .returning(Item)
        )
        item = result.scalar_one_or_none()
        if item is not None:
            return MutationResult.updated(item)
        current = await self.get_active_by_id(owner_id=owner_id, item_id=item_id)
        if current is None:
            return MutationResult.not_found()
        return MutationResult.version_conflict(current.version)

    async def soft_delete_cas(
        self,
        *,
        owner_id: str,
        item_id: str,
        expected_version: int,
        deleted_by: str,
    ) -> MutationResult[Item]:
        result = await self._session.execute(
            update(Item)
            .where(
                Item.owner_id == owner_id,
                Item.id == item_id,
                Item.version == expected_version,
                Item.deleted_at.is_(None),
            )
            .values(
                deleted_at=datetime.now(timezone.utc),
                deleted_by=deleted_by,
                version=Item.version + 1,
            )
            .returning(Item)
        )
        item = result.scalar_one_or_none()
        if item is not None:
            return MutationResult.updated(item)
        current = await self.get_active_by_id(owner_id=owner_id, item_id=item_id)
        if current is None:
            return MutationResult.not_found()
        return MutationResult.version_conflict(current.version)

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.item_repository import ItemRepository


class UnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.session: AsyncSession | None = None
        self.items: ItemRepository | None = None

    async def __aenter__(self) -> "UnitOfWork":
        self.session = self._session_factory()
        self.items = ItemRepository(self.session)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.session is None:
            return
        try:
            if exc_type is not None:
                await self.rollback()
        finally:
            await self.session.close()

    async def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("unit of work is not entered")
        await self.session.commit()

    async def rollback(self) -> None:
        if self.session is None:
            raise RuntimeError("unit of work is not entered")
        await self.session.rollback()


UowFactory = Callable[[], UnitOfWork]


def uow_factory_from_session_factory(session_factory: async_sessionmaker[AsyncSession]) -> UowFactory:
    return lambda: UnitOfWork(session_factory)

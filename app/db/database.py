from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import AppSettings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_db_engine(settings: AppSettings) -> AsyncEngine:
    app_settings = settings or get_settings()
    engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
    connect_args = {} if app_settings.database.ssl else {"ssl": False}
    if app_settings.database.url.startswith("sqlite+aiosqlite://"):
        connect_args = {}
    else:
        engine_kwargs["pool_size"] = app_settings.database.pool_size
        engine_kwargs["max_overflow"] = app_settings.database.max_overflow
    return create_async_engine(
        app_settings.database.url,
        connect_args=connect_args,
        **engine_kwargs,
    )


def init_db_engine(settings: AppSettings | None = None) -> AsyncEngine:
    global _engine, _session_factory

    if _engine is not None:
        return _engine
    app_settings = settings or get_settings()
    _engine = create_db_engine(app_settings)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def close_db_engine() -> None:
    global _engine, _session_factory

    if _engine is None:
        return
    engine = _engine
    _engine = None
    _session_factory = None
    await engine.dispose()


def configure_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    global _session_factory
    _session_factory = factory


def current_session_factory() -> async_sessionmaker[AsyncSession] | None:
    return _session_factory


def clear_session_factory() -> None:
    global _session_factory
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("database session factory is not initialized")
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session

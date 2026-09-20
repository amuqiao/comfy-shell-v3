from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import AppSettings
from app.core.lifecycle import HealthCheck, HealthCheckResult
from app.db.database import (
    create_db_engine,
)


@dataclass(frozen=True)
class PostgresResource:
    engine: AsyncEngine | None
    session_factory: async_sessionmaker[AsyncSession]
    owns_engine: bool
    database_url: str | None


class PostgresProvider:
    name = "postgres"
    required = True

    async def startup(self, app: FastAPI, settings: AppSettings) -> PostgresResource:
        override = getattr(app.state, "db_session_factory_override", None)
        if override is not None:
            resource = PostgresResource(
                engine=None,
                session_factory=override,
                owns_engine=False,
                database_url=None,
            )
            app.state.db_engine = None
            app.state.db_session_factory = resource.session_factory
            return resource

        engine = create_db_engine(settings)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        resource = PostgresResource(
            engine=engine,
            session_factory=session_factory,
            owns_engine=True,
            database_url=settings.database.url,
        )
        app.state.db_engine = engine
        app.state.db_session_factory = session_factory
        return resource

    async def shutdown(self, app: FastAPI, resource: PostgresResource) -> None:
        if resource.owns_engine:
            assert resource.engine is not None
            await resource.engine.dispose()
        if hasattr(app.state, "db_engine"):
            delattr(app.state, "db_engine")
        if hasattr(app.state, "db_session_factory"):
            delattr(app.state, "db_session_factory")

    def health_check(self, resource: PostgresResource) -> HealthCheck | None:
        async def check() -> HealthCheckResult:
            if resource.owns_engine and not (resource.database_url or "").startswith("postgresql+asyncpg://"):
                return HealthCheckResult("postgres", "failed", {"reason": "non_postgres_database_url"})
            try:
                async with resource.session_factory() as session:
                    await session.execute(text("SELECT 1"))
            except Exception as exc:
                return HealthCheckResult("postgres", "failed", {"reason": type(exc).__name__})
            return HealthCheckResult(
                "postgres",
                "ok",
                {"configured": True, "test_override": not resource.owns_engine},
            )

        return HealthCheck(name="postgres", check=check, required=self.required)

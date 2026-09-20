import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.core.lifecycle import HealthCheckRegistry, LifecycleProviderRegistry
from app.db.database import current_session_factory
from app.db.unit_of_work import UnitOfWork
from app.integrations.http_client import get_http_client
from app.integrations.redis import get_redis_client
from app.integrations.storage import DisabledObjectStorage, LocalObjectStorage, get_storage
from app.main import create_app


class RecordingProvider:
    def __init__(self, name: str, events: list[str], *, fail: bool = False) -> None:
        self.name = name
        self.required = True
        self._events = events
        self._fail = fail

    async def startup(self, app, settings):
        self._events.append(f"start:{self.name}")
        if self._fail:
            raise RuntimeError(self.name)
        return self.name

    async def shutdown(self, app, resource):
        self._events.append(f"stop:{self.name}")

    def health_check(self, resource):
        return None


def local_storage_settings(tmp_path) -> AppSettings:
    return AppSettings(
        security={"service_api_key": "test-service-key"},
        database={"url": "sqlite+aiosqlite:///:memory:"},
        storage={"backend": "local", "local_path": str(tmp_path / "objects")},
        observability={"access_log_enabled": False},
    )


@pytest.mark.asyncio
async def test_lifecycle_startup_failure_cleans_started_providers():
    events: list[str] = []
    registry = LifecycleProviderRegistry()
    registry.register(RecordingProvider("one", events))
    registry.register(RecordingProvider("two", events, fail=True))

    with pytest.raises(RuntimeError, match="two"):
        await registry.startup(FastAPI(), AppSettings(), HealthCheckRegistry())

    assert events == ["start:one", "start:two", "stop:one"]


def test_app_lifespan_starts_and_stops_providers(tmp_path):
    app = create_app(local_storage_settings(tmp_path))
    with TestClient(app) as client:
        assert get_redis_client(client.app).values == {}
        assert isinstance(get_storage(client.app), LocalObjectStorage)
        assert not get_http_client(client.app).is_closed

    assert not hasattr(app.state, "redis")
    assert not hasattr(app.state, "object_storage")
    assert not hasattr(app.state, "http_client")


@pytest.mark.asyncio
async def test_local_object_storage_roundtrip(tmp_path):
    app = create_app(local_storage_settings(tmp_path))
    with TestClient(app) as client:
        storage = get_storage(client.app)
        await storage.put("nested/example.txt", b"hello")
        assert await storage.get("nested/example.txt") == b"hello"
        await storage.delete("nested/example.txt")


@pytest.mark.asyncio
async def test_local_object_storage_rejects_escaped_keys(tmp_path):
    storage = LocalObjectStorage(tmp_path / "objects")

    with pytest.raises(ValueError, match="storage key escapes storage root"):
        await storage.put("../objects-escaped/file.txt", b"bad")


def test_disabled_storage_provider_is_explicit():
    app = create_app(
        AppSettings(
            security={"service_api_key": "test-service-key"},
            database={"url": "sqlite+aiosqlite:///:memory:"},
            storage={"backend": "disabled"},
        )
    )
    with TestClient(app) as client:
        assert isinstance(get_storage(client.app), DisabledObjectStorage)


def test_session_factory_override_is_scoped_to_app(app, sqlite_session_factory):
    previous = current_session_factory()
    app.state.db_session_factory_override = sqlite_session_factory

    with TestClient(app) as client:
        assert client.app.state.db_session_factory is sqlite_session_factory

    assert current_session_factory() is previous


def test_parallel_app_lifespans_do_not_share_database_state(test_settings):
    first = create_app(test_settings)
    second = create_app(test_settings)

    with TestClient(first) as first_client:
        first_factory = first_client.app.state.db_session_factory
        with TestClient(second):
            pass

        assert first_client.app.state.db_session_factory is first_factory


def test_unit_of_work_requires_explicit_session_factory():
    with pytest.raises(TypeError):
        UnitOfWork()


def test_redis_enabled_is_explicitly_unsupported_in_phase_3():
    app = create_app(
        AppSettings(
            security={"service_api_key": "test-service-key"},
            database={"url": "sqlite+aiosqlite:///:memory:"},
            redis={"enabled": True},
        )
    )

    with pytest.raises(RuntimeError, match="real Redis provider is not implemented"):
        with TestClient(app):
            pass

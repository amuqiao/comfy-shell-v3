import pytest
from sqlalchemy.engine import make_url

from scripts.verify import ensure_test_database
from scripts.verify.ensure_test_database import ConfigError, ensure_database, quote_identifier, require_safe_test_database


def test_require_safe_test_database_accepts_local_test_database():
    url = make_url("postgresql+asyncpg://postgres:postgres@127.0.0.1:35432/fastapi_lite_test")

    assert require_safe_test_database(url) == "fastapi_lite_test"


def test_require_safe_test_database_rejects_non_test_database():
    url = make_url("postgresql+asyncpg://postgres:postgres@127.0.0.1:35432/fastapi_lite")

    with pytest.raises(ConfigError, match="requires \\*_test database"):
        require_safe_test_database(url)


def test_require_safe_test_database_rejects_remote_host():
    url = make_url("postgresql+asyncpg://postgres:postgres@db.example.com:5432/fastapi_lite_test")

    with pytest.raises(ConfigError, match="refuses non-local database host"):
        require_safe_test_database(url)


def test_quote_identifier_escapes_double_quotes():
    assert quote_identifier('fastapi_"lite"_test') == '"fastapi_""lite""_test"'


@pytest.mark.asyncio
async def test_ensure_database_creates_missing_database(monkeypatch):
    class FakeConnection:
        def __init__(self):
            self.executed: list[str] = []
            self.closed = False

        async def fetchrow(self, _query, _database):
            return None

        async def execute(self, statement):
            self.executed.append(statement)

        async def close(self):
            self.closed = True

    connection = FakeConnection()

    async def fake_connect(**_kwargs):
        return connection

    monkeypatch.setattr(ensure_test_database.asyncpg, "connect", fake_connect)
    url = make_url("postgresql+asyncpg://postgres:postgres@127.0.0.1:35432/fastapi_lite_test")

    created = await ensure_database(url, "fastapi_lite_test")

    assert created is True
    assert connection.executed == ['CREATE DATABASE "fastapi_lite_test"']
    assert connection.closed is True


@pytest.mark.asyncio
async def test_ensure_database_keeps_existing_database(monkeypatch):
    class FakeConnection:
        def __init__(self):
            self.executed: list[str] = []
            self.closed = False

        async def fetchrow(self, _query, _database):
            return {"?column?": 1}

        async def execute(self, statement):
            self.executed.append(statement)

        async def close(self):
            self.closed = True

    connection = FakeConnection()

    async def fake_connect(**_kwargs):
        return connection

    monkeypatch.setattr(ensure_test_database.asyncpg, "connect", fake_connect)
    url = make_url("postgresql+asyncpg://postgres:postgres@127.0.0.1:35432/fastapi_lite_test")

    created = await ensure_database(url, "fastapi_lite_test")

    assert created is False
    assert connection.executed == []
    assert connection.closed is True

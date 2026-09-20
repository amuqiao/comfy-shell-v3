from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg
from sqlalchemy.engine import URL, make_url

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings


LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1", "postgres"}


class ConfigError(Exception):
    pass


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def require_safe_test_database(url: URL) -> str:
    if url.host not in LOCAL_HOSTS:
        raise ConfigError(f"PostgreSQL integration refuses non-local database host: {url.host}")
    database = url.database or ""
    if not database.endswith("_test"):
        raise ConfigError(f"PostgreSQL integration requires *_test database, got: {database}")
    return database


async def database_exists(connection: asyncpg.Connection, database: str) -> bool:
    row = await connection.fetchrow("SELECT 1 FROM pg_database WHERE datname = $1", database)
    return row is not None


async def ensure_database(url: URL, database: str) -> bool:
    connection = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database="postgres",
        ssl=False,
    )
    try:
        if await database_exists(connection, database):
            return False
        await connection.execute(f"CREATE DATABASE {quote_identifier(database)}")
        return True
    finally:
        await connection.close()


async def async_main() -> int:
    try:
        url = make_url(get_settings().database.url)
        database = require_safe_test_database(url)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    created = await ensure_database(url, database)
    print(f"OK test-database database={database} created={str(created).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))

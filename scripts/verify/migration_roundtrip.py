from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
from sqlalchemy.engine import URL, make_url

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.base import Base
import app.models  # noqa: F401
from app.models import REGISTERED_MODELS


def require_local(url: URL) -> None:
    if url.host not in {"127.0.0.1", "localhost", "0.0.0.0", "postgres"}:
        raise SystemExit(f"refuse to run migration roundtrip against non-local database host: {url.host}")


async def admin_connect(url: URL) -> asyncpg.Connection:
    return await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database="postgres",
        ssl=False,
    )


async def create_database(admin_url: URL, database_name: str) -> None:
    connection = await admin_connect(admin_url)
    try:
        await connection.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await connection.close()


async def drop_database(admin_url: URL, database_name: str) -> None:
    connection = await admin_connect(admin_url)
    try:
        await connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        await connection.close()


def run_alembic(command: str, revision: str, *, target_url: URL) -> None:
    env = os.environ.copy()
    env["DATABASE__URL"] = target_url.render_as_string(hide_password=False)
    env["PYTHONPATH"] = f"{ROOT_DIR}{os.pathsep}{env.get('PYTHONPATH', '')}"
    result = subprocess.run(
        ["uv", "run", "alembic", command, revision],
        cwd=ROOT_DIR,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        raise SystemExit(result.returncode)


async def table_names(target_url: URL) -> set[str]:
    connection = await asyncpg.connect(
        user=target_url.username,
        password=target_url.password,
        host=target_url.host,
        port=target_url.port,
        database=target_url.database,
        ssl=False,
    )
    try:
        rows = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        return {str(row["tablename"]) for row in rows}
    finally:
        await connection.close()


def registered_application_tables() -> set[str]:
    registered = {model.__table__.name for model in REGISTERED_MODELS}
    metadata = set(Base.metadata.tables)
    if not registered:
        raise AssertionError("registered metadata has no application tables")
    if registered != metadata:
        raise AssertionError(
            f"registered models drift from metadata: registered={sorted(registered)} metadata={sorted(metadata)}"
        )
    return registered


async def assert_head_schema(target_url: URL) -> None:
    tables = await table_names(target_url)
    expected = registered_application_tables()
    missing = expected - tables
    if missing:
        raise AssertionError(f"head schema missing application tables: {sorted(missing)}")
    unexpected = tables - expected - {"alembic_version"}
    if unexpected:
        raise AssertionError(f"head schema has unexpected application tables: {sorted(unexpected)}")
    if "alembic_version" not in tables:
        raise AssertionError("head schema missing alembic_version table")


async def assert_base_schema(target_url: URL) -> None:
    tables = await table_names(target_url)
    unexpected = tables - {"alembic_version"}
    if unexpected:
        raise AssertionError(f"base schema still has application tables: {sorted(unexpected)}")


async def main() -> None:
    base_url = make_url(get_settings().database.url)
    require_local(base_url)
    database_name = f"{base_url.database}_migration_rt_{uuid.uuid4().hex[:8]}"
    target_url = base_url.set(database=database_name)

    await create_database(base_url, database_name)
    try:
        run_alembic("upgrade", "head", target_url=target_url)
        await assert_head_schema(target_url)
        print("OK        upgrade    head")

        run_alembic("downgrade", "base", target_url=target_url)
        await assert_base_schema(target_url)
        print("OK        downgrade  base")

        run_alembic("upgrade", "head", target_url=target_url)
        await assert_head_schema(target_url)
        print("OK        reupgrade  head")
    finally:
        await drop_database(base_url, database_name)


if __name__ == "__main__":
    asyncio.run(main())

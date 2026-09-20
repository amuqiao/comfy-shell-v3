import pytest

from scripts.verify import migration_roundtrip


@pytest.mark.asyncio
async def test_assert_head_schema_accepts_registered_metadata_tables(monkeypatch):
    async def table_names(_target_url):
        return set(migration_roundtrip.Base.metadata.tables) | {"alembic_version"}

    monkeypatch.setattr(migration_roundtrip, "table_names", table_names)

    await migration_roundtrip.assert_head_schema(None)


@pytest.mark.asyncio
async def test_assert_head_schema_detects_missing_registered_table(monkeypatch):
    expected = set(migration_roundtrip.Base.metadata.tables)
    missing = next(iter(expected))

    async def table_names(_target_url):
        return (expected - {missing}) | {"alembic_version"}

    monkeypatch.setattr(migration_roundtrip, "table_names", table_names)

    with pytest.raises(AssertionError, match="head schema missing application tables"):
        await migration_roundtrip.assert_head_schema(None)


@pytest.mark.asyncio
async def test_assert_head_schema_detects_unexpected_application_table(monkeypatch):
    async def table_names(_target_url):
        return set(migration_roundtrip.Base.metadata.tables) | {"alembic_version", "orphan_table"}

    monkeypatch.setattr(migration_roundtrip, "table_names", table_names)

    with pytest.raises(AssertionError, match="head schema has unexpected application tables"):
        await migration_roundtrip.assert_head_schema(None)


def test_registered_models_match_metadata_tables():
    registered = {model.__table__.name for model in migration_roundtrip.REGISTERED_MODELS}

    assert registered == set(migration_roundtrip.Base.metadata.tables)

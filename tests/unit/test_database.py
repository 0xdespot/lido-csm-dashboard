"""Tests for the database module."""

import asyncio
import pytest

import src.data.database as db_module
from src.data.database import init_db


@pytest.fixture(autouse=True)
def reset_db_state():
    """Reset database initialization state between tests."""
    db_module._db_initialized = False
    if hasattr(db_module, "_db_init_lock"):
        db_module._db_init_lock = asyncio.Lock()
    yield
    db_module._db_initialized = False


@pytest.mark.asyncio
async def test_concurrent_init_db_initializes_only_once(tmp_path, monkeypatch):
    """init_db called concurrently must not initialize the DB schema more than once."""
    monkeypatch.setattr(
        "src.data.database.get_db_path", lambda: _async_return(tmp_path / "test.db")
    )

    init_count = 0
    original_execute = None

    # Patch to count how many times the CREATE TABLE statement is executed
    import aiosqlite

    original_connect = aiosqlite.connect

    class CountingConnection:
        def __init__(self, conn):
            self._conn = conn
            self.row_factory = None

        async def execute(self, sql, *args, **kwargs):
            nonlocal init_count
            if "CREATE TABLE" in sql:
                init_count += 1
            return await self._conn.execute(sql, *args, **kwargs)

        async def commit(self):
            return await self._conn.commit()

        async def close(self):
            return await self._conn.close()

        async def __aenter__(self):
            await self._conn.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self._conn.__aexit__(*args)

    import contextlib

    @contextlib.asynccontextmanager
    async def patched_connect(path, **kwargs):
        async with original_connect(path, **kwargs) as conn:
            yield CountingConnection(conn)

    monkeypatch.setattr(aiosqlite, "connect", patched_connect)

    # Fire 10 concurrent calls to init_db — only 1 CREATE TABLE should happen
    await asyncio.gather(*[init_db() for _ in range(10)])

    assert init_count == 1, f"Expected CREATE TABLE once, got {init_count} times"


async def _async_return(value):
    return value

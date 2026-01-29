"""SQLite database for persisting saved operators."""

import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from ..core.config import get_settings

_db_initialized = False


async def get_db_path() -> Path:
    """Get the database file path, creating parent directories if needed."""
    settings = get_settings()
    db_path = settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


async def init_db() -> None:
    """Initialize the database schema."""
    global _db_initialized
    if _db_initialized:
        return

    db_path = await get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS saved_operators (
                operator_id INTEGER PRIMARY KEY,
                manager_address TEXT NOT NULL,
                reward_address TEXT NOT NULL,
                data_json TEXT NOT NULL,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
    _db_initialized = True


async def save_operator(operator_id: int, data: dict) -> None:
    """Save or update an operator in the database.

    Args:
        operator_id: The operator ID
        data: The full operator data dictionary (from API response)
    """
    await init_db()
    db_path = await get_db_path()

    manager_address = data.get("manager_address", "")
    reward_address = data.get("reward_address", "")
    data_json = json.dumps(data)
    now = datetime.utcnow().isoformat()

    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            INSERT INTO saved_operators (operator_id, manager_address, reward_address, data_json, saved_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(operator_id) DO UPDATE SET
                manager_address = excluded.manager_address,
                reward_address = excluded.reward_address,
                data_json = excluded.data_json,
                updated_at = excluded.updated_at
        """, (operator_id, manager_address, reward_address, data_json, now, now))
        await db.commit()


async def get_saved_operators() -> list[dict]:
    """Get all saved operators with their cached data.

    Returns:
        List of operator data dictionaries with added metadata (saved_at, updated_at)
    """
    try:
        await init_db()
        db_path = await get_db_path()

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT operator_id, data_json, saved_at, updated_at
                FROM saved_operators
                ORDER BY saved_at DESC
            """) as cursor:
                rows = await cursor.fetchall()

        result = []
        for row in rows:
            try:
                data = json.loads(row["data_json"])
                data["_saved_at"] = row["saved_at"]
                data["_updated_at"] = row["updated_at"]
                result.append(data)
            except json.JSONDecodeError:
                # Skip corrupted entries
                continue

        return result
    except Exception as e:
        print(f"Database error in get_saved_operators: {e}")
        return []


async def delete_operator(operator_id: int) -> bool:
    """Remove an operator from the saved list.

    Args:
        operator_id: The operator ID to remove

    Returns:
        True if the operator was deleted, False if not found
    """
    await init_db()
    db_path = await get_db_path()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM saved_operators WHERE operator_id = ?",
            (operator_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def is_operator_saved(operator_id: int) -> bool:
    """Check if an operator is saved.

    Args:
        operator_id: The operator ID to check

    Returns:
        True if the operator is saved, False otherwise
    """
    await init_db()
    db_path = await get_db_path()

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT 1 FROM saved_operators WHERE operator_id = ?",
            (operator_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None


async def update_operator_data(operator_id: int, data: dict) -> bool:
    """Update the cached data for a saved operator.

    Args:
        operator_id: The operator ID
        data: The new operator data dictionary

    Returns:
        True if updated, False if operator not found
    """
    await init_db()
    db_path = await get_db_path()

    manager_address = data.get("manager_address", "")
    reward_address = data.get("reward_address", "")
    data_json = json.dumps(data)
    now = datetime.utcnow().isoformat()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("""
            UPDATE saved_operators
            SET manager_address = ?, reward_address = ?, data_json = ?, updated_at = ?
            WHERE operator_id = ?
        """, (manager_address, reward_address, data_json, now, operator_id))
        await db.commit()
        return cursor.rowcount > 0

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Tuple

import aiosqlite

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime(ISO_FORMAT)


class Storage:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._lock:
            async with aiosqlite.connect(self._database_path) as db:
                await db.executescript(
                    """
                    PRAGMA journal_mode=WAL;
                    PRAGMA foreign_keys=ON;

                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_seen TEXT NOT NULL,
                        last_seen TEXT NOT NULL,
                        check_count INTEGER NOT NULL DEFAULT 0,
                        is_banned INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS checks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        query TEXT NOT NULL,
                        status TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        raw_response TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_checks_user ON checks(user_id, created_at DESC);
                    """
                )
                await db.commit()

    async def add_or_update_user(
        self, user_id: int, username: Optional[str]
    ) -> None:
        timestamp = utc_now()
        async with self._lock:
            async with aiosqlite.connect(self._database_path) as db:
                await db.execute(
                    """
                    INSERT INTO users (user_id, username, first_seen, last_seen, check_count)
                    VALUES (?, ?, ?, ?, 0)
                    ON CONFLICT(user_id) DO UPDATE SET
                        username=excluded.username,
                        last_seen=excluded.last_seen;
                    """,
                    (user_id, username, timestamp, timestamp),
                )
                await db.commit()

    async def increment_check_count(self, user_id: int) -> None:
        async with self._lock:
            async with aiosqlite.connect(self._database_path) as db:
                await db.execute(
                    """
                    UPDATE users
                    SET check_count = check_count + 1,
                        last_seen = ?
                    WHERE user_id = ?;
                    """,
                    (utc_now(), user_id),
                )
                await db.commit()

    async def record_check(
        self,
        user_id: int,
        query: str,
        status: str,
        summary: str,
        raw_response: Optional[str] = None,
    ) -> None:
        async with self._lock:
            async with aiosqlite.connect(self._database_path) as db:
                await db.execute(
                    """
                    INSERT INTO checks (user_id, query, status, summary, raw_response, created_at)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (user_id, query, status, summary, raw_response, utc_now()),
                )
                await db.commit()

    async def get_recent_checks(
        self, limit: int = 10
    ) -> List[Dict[str, Any]]:
        async with self._lock:
            async with aiosqlite.connect(self._database_path) as db:
                cursor = await db.execute(
                    """
                    SELECT c.id, c.user_id, c.query, c.status, c.summary, c.created_at, u.username
                    FROM checks c
                    JOIN users u ON u.user_id = c.user_id
                    ORDER BY c.created_at DESC
                    LIMIT ?;
                    """,
                    (limit,),
                )
                rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "user_id": row[1],
                "query": row[2],
                "status": row[3],
                "summary": row[4],
                "created_at": row[5],
                "username": row[6],
            }
            for row in rows
        ]

    async def set_user_ban(self, user_id: int, should_ban: bool) -> bool:
        async with self._lock:
            async with aiosqlite.connect(self._database_path) as db:
                cursor = await db.execute(
                    "UPDATE users SET is_banned = ? WHERE user_id = ?;",
                    (1 if should_ban else 0, user_id),
                )
                await db.commit()
                rows_changed = cursor.rowcount
        return bool(rows_changed)

    async def is_user_banned(self, user_id: int) -> bool:
        async with self._lock:
            async with aiosqlite.connect(self._database_path) as db:
                cursor = await db.execute(
                    "SELECT is_banned FROM users WHERE user_id = ?;",
                    (user_id,),
                )
                row = await cursor.fetchone()
        return bool(row and row[0])

    async def get_stats(self) -> Dict[str, Any]:
        async with self._lock:
            async with aiosqlite.connect(self._database_path) as db:
                cursor = await db.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM users),
                        (SELECT COUNT(*) FROM users WHERE is_banned = 1),
                        (SELECT SUM(check_count) FROM users)
                    ;
                    """
                )
                row = await cursor.fetchone()
        total_users = row[0] if row and row[0] is not None else 0
        banned_users = row[1] if row and row[1] is not None else 0
        total_checks = row[2] if row and row[2] is not None else 0
        return {
            "total_users": int(total_users),
            "banned_users": int(banned_users),
            "total_checks": int(total_checks),
        }

    async def list_banned_users(self) -> List[Dict[str, Any]]:
        async with self._lock:
            async with aiosqlite.connect(self._database_path) as db:
                cursor = await db.execute(
                    """
                    SELECT user_id, username, first_seen, last_seen
                    FROM users
                    WHERE is_banned = 1
                    ORDER BY last_seen DESC;
                    """
                )
                rows = await cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "username": row[1],
                "first_seen": row[2],
                "last_seen": row[3],
            }
            for row in rows
        ]

    async def get_active_user_ids(self) -> List[int]:
        async with self._lock:
            async with aiosqlite.connect(self._database_path) as db:
                cursor = await db.execute(
                    "SELECT user_id FROM users WHERE is_banned = 0;"
                )
                rows = await cursor.fetchall()
        return [row[0] for row in rows]

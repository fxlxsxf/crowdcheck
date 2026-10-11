"""SQLite cache, one file, created on first use.

Values are JSON. Each entry records when it was fetched, and a read only returns
it while it is younger than the namespace's TTL in config.CACHE_TTL.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_MISS = object()


class Cache:
    MISS = _MISS

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS cache (ns TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,"
            " fetched_at REAL NOT NULL, PRIMARY KEY (ns, key))"
        )
        self.db.commit()

    def get(self, ns: str, key: str, ttl_seconds: float, now: float | None = None) -> Any:
        row = self.db.execute("SELECT value, fetched_at FROM cache WHERE ns = ? AND key = ?", (ns, key)).fetchone()
        if row is None:
            return _MISS
        value, fetched_at = row
        if (now if now is not None else time.time()) - fetched_at > ttl_seconds:
            return _MISS
        return json.loads(value)

    def set(self, ns: str, key: str, value: Any, now: float | None = None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO cache (ns, key, value, fetched_at) VALUES (?, ?, ?, ?)",
            (ns, key, json.dumps(value), now if now is not None else time.time()),
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

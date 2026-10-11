"""SQLite decision history. One row per decision, stored as JSON."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .models import Decision


class DecisionStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, created_at REAL NOT NULL, data TEXT NOT NULL)"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_created ON decisions(created_at)")
        self._db.commit()

    def save(self, d: Decision) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO decisions (id, created_at, data) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (d.id, d.created_at, d.model_dump_json()),
            )
            self._db.commit()

    def get(self, decision_id: str) -> Decision | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM decisions WHERE id = ?", (decision_id,)).fetchone()
        return Decision.model_validate_json(row[0]) if row else None

    def list(self, limit: int = 200) -> list[Decision]:
        with self._lock:
            rows = self._db.execute(
                "SELECT data FROM decisions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Decision.model_validate_json(r[0]) for r in rows]

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM decisions")
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

"""SQLite 访问层：连接、建表、行转 dict。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import config

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"


def connect() -> sqlite3.Connection:
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(conversations)")}
        if "source" not in columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN source TEXT NOT NULL DEFAULT 'web'")
        if "focus_seconds" not in columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN focus_seconds INTEGER")
        conn.commit()


def rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]

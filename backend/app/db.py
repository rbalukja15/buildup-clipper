"""SQLite access.

Short-lived connections per operation (WAL + busy timeout) keep the async API
handlers and the background worker from stepping on each other without a
connection pool or an ORM.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import get_settings

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS match (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    opponent     TEXT NOT NULL DEFAULT '',
    date         TEXT,
    source_type  TEXT NOT NULL CHECK (source_type IN ('file', 'youtube')),
    source_url   TEXT,
    file_path    TEXT,
    proxy_path   TEXT,
    duration_s   REAL,
    fps          REAL,
    ingest_state TEXT NOT NULL DEFAULT 'pending'
                 CHECK (ingest_state IN ('pending', 'downloading', 'probing', 'proxying', 'ready', 'failed')),
    ingest_error TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tag (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id   INTEGER NOT NULL REFERENCES match(id) ON DELETE CASCADE,
    t_start    REAL NOT NULL,
    t_end      REAL NOT NULL,
    category   TEXT NOT NULL DEFAULT 'gk_buildup',
    source     TEXT NOT NULL DEFAULT 'manual',
    note       TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tag_match ON tag(match_id, t_start);

CREATE TABLE IF NOT EXISTS clip (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_id       INTEGER NOT NULL UNIQUE REFERENCES tag(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    order_index  INTEGER NOT NULL DEFAULT 0,
    review_path  TEXT,
    final_path   TEXT,
    render_state TEXT NOT NULL DEFAULT 'pending'
                 CHECK (render_state IN ('pending', 'rendering', 'ready', 'failed')),
    render_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_clip_tag ON clip(tag_id);

CREATE TABLE IF NOT EXISTS export (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    file_path    TEXT,
    state        TEXT NOT NULL DEFAULT 'pending'
                 CHECK (state IN ('pending', 'rendering', 'ready', 'failed')),
    error        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS export_clip (
    export_id INTEGER NOT NULL REFERENCES export(id) ON DELETE CASCADE,
    clip_id   INTEGER NOT NULL REFERENCES clip(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    PRIMARY KEY (export_id, clip_id)
);
"""


def _connect_path(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = _connect_path(get_settings().db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """Explicit transaction -- rolls back on exception."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def init_db() -> None:
    settings = get_settings()
    settings.ensure_dirs()
    conn = _connect_path(settings.db_path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
    _recover_interrupted()


def _recover_interrupted() -> None:
    """A crash mid-render leaves rows stuck in a transient state; reset them so
    the work is simply redone rather than hanging forever in the UI."""
    with connect() as conn:
        conn.execute(
            "UPDATE match SET ingest_state = 'failed', ingest_error = 'interrupted by restart' "
            "WHERE ingest_state IN ('downloading', 'probing', 'proxying')"
        )
        conn.execute("UPDATE clip SET render_state = 'pending' WHERE render_state = 'rendering'")
        conn.execute(
            "UPDATE export SET state = 'failed', error = 'interrupted by restart' WHERE state = 'rendering'"
        )


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]

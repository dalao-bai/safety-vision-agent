"""SQLite connection helper and schema initialization (U2).

Keeps connection setup small and explicit: foreign keys on, row factory for
dict-like access, and idempotent schema creation from schema.sql.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys enabled and row access by name.

    The parent directory is created if needed so a fresh ``runtime/`` works
    without manual setup.
    """
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False: FastAPI runs sync dependencies in a threadpool
    # while async endpoints run on the event loop, so one request's connection
    # may be touched from more than one thread. Each request still gets its own
    # connection and never shares it concurrently, so this is safe here.
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables/indexes from schema.sql. Idempotent."""
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()

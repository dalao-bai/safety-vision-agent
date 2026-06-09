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

    # conversations 新增列迁移（SQLite 不支持 ADD COLUMN IF NOT EXISTS，Python 侧判断）
    existing_cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(conversations)").fetchall()
    }
    new_cols = [
        ("user_id",   "ALTER TABLE conversations ADD COLUMN user_id TEXT REFERENCES users(id)"),
        ("confirmed", "ALTER TABLE conversations ADD COLUMN confirmed INTEGER DEFAULT NULL"),
    ]
    for col_name, ddl in new_cols:
        if col_name not in existing_cols:
            conn.execute(ddl)
    conn.commit()

    # user_id 列就绪后才能建这个索引（schema.sql 阶段列尚不存在）
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_user_date "
        "ON conversations(user_id, created_at)"
    )
    conn.commit()

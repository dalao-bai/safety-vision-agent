"""FastAPI dependency providers (U8).

Centralizes construction of the per-request DB connection and the model
clients so routes stay thin and tests can override them via
``app.dependency_overrides``.
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from typing import Iterator

from app.core.config import Settings, get_settings
from app.db.sqlite import connect, init_db
from app.services.regulation_store import RegulationStore
from app.services.responses_client import ResponsesClient


def get_app_settings() -> Settings:
    """Application settings (cached in config module)."""
    return get_settings()


def get_db() -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection for the request, ensuring the schema exists."""
    settings = get_settings()
    conn = connect(settings.database_path)
    init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


@lru_cache(maxsize=1)
def _vlm_client() -> ResponsesClient:
    s = get_settings()
    return ResponsesClient(s.openai_api_base_url, s.openai_api_key)


def get_vlm_client() -> ResponsesClient:
    return _vlm_client()


@lru_cache(maxsize=1)
def _regulation_store() -> RegulationStore:
    s = get_settings()
    vlm = _vlm_client()
    return RegulationStore(
        chroma_dir=s.chroma_dir,
        embed_fn=lambda texts: vlm.embed(s.embedding_model, texts),
    )


def get_regulation_store() -> RegulationStore:
    """Return the application-lifetime RegulationStore singleton.

    The ChromaDB PersistentClient is expensive to open and holds a file lock;
    constructing it once at startup and reusing it across requests avoids
    file-descriptor exhaustion and lock contention under concurrency.
    """
    return _regulation_store()

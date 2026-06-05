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
def _agent_client() -> ResponsesClient:
    s = get_settings()
    return ResponsesClient(s.openai_api_base_url, s.openai_api_key)


@lru_cache(maxsize=1)
def _vlm_client() -> ResponsesClient:
    s = get_settings()
    return ResponsesClient(s.openai_api_base_url, s.openai_api_key)


def get_agent_client() -> ResponsesClient:
    return _agent_client()


def get_vlm_client() -> ResponsesClient:
    return _vlm_client()

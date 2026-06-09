"""Auth dependencies for v0.2 protected routes (U8).

Provides the current authenticated user (decoded from the Bearer JWT) and a
per-request annotation.db connection. Kept separate from dependencies.py so the
auth surface is easy to find and override in tests.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterator

from fastapi import Depends, Header, HTTPException

from app.api.dependencies import get_db
from app.core.config import Settings, get_settings
from app.db import annotation as anno
from app.db import repositories as repo
from app.services.security import TokenError, decode_access_token


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated principal for a request."""

    id: str
    username: str


def get_current_user(
    authorization: str | None = Header(None),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Resolve the current user from the ``Authorization: Bearer <jwt>`` header.

    Raises 401 for a missing/malformed header, an invalid/expired token, or a
    token whose subject no longer maps to a real user.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing or malformed Authorization header")

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token, settings.jwt_secret, settings.jwt_algorithm)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from exc

    user_id = payload.get("sub")
    if not user_id or repo.get_user_by_id(conn, user_id) is None:
        raise HTTPException(status_code=401, detail="token subject is not a known user")

    return CurrentUser(id=user_id, username=payload.get("username", ""))


def get_annotation_conn(
    settings: Settings = Depends(get_settings),
) -> Iterator[sqlite3.Connection]:
    """Yield a per-request connection to the independent annotation.db."""
    conn = anno.connect_annotation(settings.annotation_db_path)
    try:
        yield conn
    finally:
        conn.close()

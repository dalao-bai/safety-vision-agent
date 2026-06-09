"""Security primitives for v0.2 auth: API-key hashing and JWT tokens.

Auth model is intentionally light (enterprise-internal, username + static API
key, no passwords). The API key is never stored in plaintext — only a salted
hash — and JWTs are signed with JWT_SECRET so they cannot be forged.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

# Fixed application salt for the API-key hash. The keys are high-entropy random
# secrets (not user-chosen passwords), so a per-record salt + slow KDF buys
# little here; a keyed SHA-256 resists rainbow tables and is fast to verify.
_HASH_SALT = b"construction-safety-agent-v0.2"


def hash_api_key(api_key: str) -> str:
    """Return a stable hex digest of the API key. Never store plaintext keys."""
    return hashlib.sha256(_HASH_SALT + api_key.encode("utf-8")).hexdigest()


def verify_api_key(api_key: str, stored_hash: str) -> bool:
    """Constant-time comparison of an API key against its stored hash."""
    return hmac.compare_digest(hash_api_key(api_key), stored_hash)


def create_access_token(
    user_id: str,
    username: str,
    secret: str,
    algorithm: str = "HS256",
    expire_minutes: int = 60 * 24,
    *,
    now: datetime | None = None,
) -> str:
    """Sign a JWT carrying the user identity. ``now`` is injectable for tests."""
    issued = now or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "username": username,
        "iat": issued,
        "exp": issued + timedelta(minutes=expire_minutes),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, expired, or has a bad signature."""


def decode_access_token(
    token: str, secret: str, algorithm: str = "HS256"
) -> dict[str, Any]:
    """Verify and decode a JWT. Raises TokenError on any validation failure."""
    try:
        return jwt.decode(token, secret, algorithms=[algorithm])
    except JWTError as exc:
        raise TokenError(str(exc)) from exc

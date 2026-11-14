"""Portfolio access keys. The key is shown once, at creation; only its SHA-256 is stored, so a
leaked database does not open anyone's portfolio."""

from __future__ import annotations

import hashlib
import hmac
import secrets

PREFIX = "tp_"


def new_key() -> str:
    return PREFIX + secrets.token_urlsafe(24)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.strip().encode()).hexdigest()


def matches(key: str | None, key_hash: str) -> bool:
    return bool(key) and hmac.compare_digest(hash_key(key or ""), key_hash)

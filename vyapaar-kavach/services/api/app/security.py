"""Password hashing and session token helpers.

Uses PBKDF2-HMAC-SHA256 from the standard library so the demo needs no extra
crypto dependencies. Tokens are opaque `secrets` strings stored server-side.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

_ITERATIONS = 120_000


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), _ITERATIONS
        ).hex()
        return hmac.compare_digest(candidate, digest_hex)
    except ValueError:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_id(prefix: str) -> str:
    """Human-friendly unique object ids, e.g. `case_4f9a2c1b88e7`."""
    return f"{prefix}_{secrets.token_hex(6)}"

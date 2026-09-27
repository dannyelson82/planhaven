"""Random secrets: generation and storage form (SECURITY.md §7.3).

Tokens are 256-bit random values. Only a SHA-256 hash is stored, so a database dump doesn't
reveal usable tokens. Comparison happens by looking up the hash (an index), not by comparing
strings in Python.
"""

import hashlib
import hmac
import secrets

SETUP_PREFIX = "phv_setup_"


def new_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def matches(token: str, stored_hash: bytes) -> bool:
    return hmac.compare_digest(token_hash(token), stored_hash)

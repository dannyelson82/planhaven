"""Password policy and hashing (SECURITY.md §7.1).

Policy: 12 to 256 characters, no composition rules, not a common or breached password, not
built from the user's own email or name. Hashing: Argon2id at or above the OWASP minimums;
parameters are stored in each hash, so they can be raised and old hashes upgraded on login.
"""

import gzip
import unicodedata
from functools import cache
from importlib import resources

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 256  # bounds hashing work per request

# OWASP Password Storage Cheat Sheet: Argon2id, m = 19 MiB, t = 2, p = 1.
_hasher = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)

# Verified against when an account doesn't exist, so a missing account takes as long as a
# wrong password (no user enumeration by timing, SECURITY.md §7.1).
_DUMMY_HASH = _hasher.hash("planhaven-timing-equalizer-not-a-real-password")


class PasswordPolicyError(ValueError):
    """The password doesn't meet the policy. The message is safe to show the user."""


def normalize(password: str) -> str:
    """NFKC, so the same password typed on different devices hashes the same."""
    return unicodedata.normalize("NFKC", password)


@cache
def _common_passwords() -> frozenset[str]:
    data = resources.files("app.auth").joinpath("data/common-passwords.txt.gz").read_bytes()
    return frozenset(gzip.decompress(data).decode("utf-8", "replace").splitlines())


def check_policy(password: str, *, email: str = "", display_name: str = "") -> None:
    password = normalize(password)
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"Use at most {MAX_LENGTH} characters.")
    lowered = password.lower()
    if len(set(lowered)) < 4:
        raise PasswordPolicyError("Use a password with more variety.")
    if lowered in _common_passwords():
        raise PasswordPolicyError("This password is too common. Choose another.")
    personal = [email.lower(), email.lower().split("@")[0], display_name.lower()]
    if any(len(p) >= 4 and p in lowered for p in personal):
        raise PasswordPolicyError("Don't include your email address or name.")


def hash_password(password: str) -> str:
    return _hasher.hash(normalize(password))


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Constant-work check. Pass None for a missing account: a dummy hash is verified so the
    timing matches."""
    candidate = normalize(password)[: MAX_LENGTH * 4]
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, candidate) and stored_hash is not None
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)

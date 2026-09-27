"""Rate limits for authentication (SECURITY.md §7.11).

Limits are per client IP, per account *from that IP* (so an attacker elsewhere can't lock a
real user out), and a looser per-account limit across all IPs (slows distributed guessing).
Account keys use a hash of the normalized email, so no addresses are stored.
"""

import hashlib
from dataclasses import dataclass

from app.core import security_log
from app.db import rate_limits as store
from app.db.database import Database


@dataclass(frozen=True, slots=True)
class Limit:
    name: str
    capacity: float
    per_second: float


LOGIN_IP = Limit("login-ip", capacity=20, per_second=1 / 30)
LOGIN_ACCOUNT_IP = Limit("login-acct-ip", capacity=5, per_second=1 / 60)
LOGIN_ACCOUNT = Limit("login-acct", capacity=50, per_second=1 / 60)
SETUP_IP = Limit("setup-ip", capacity=5, per_second=1 / 60)
PASSKEY_LOGIN_IP = Limit("passkey-ip", capacity=20, per_second=1 / 30)
MFA_USER = Limit("mfa-user", capacity=10, per_second=1 / 60)


class RateLimitedError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many attempts. Try again later.")
        self.retry_after = retry_after


def account_key(email: str) -> str:
    return hashlib.sha256(b"planhaven account\x00" + email.encode()).hexdigest()[:32]


def key(limit: Limit, *parts: object) -> str:
    return ":".join([limit.name, *(str(p) if p is not None else "unknown" for p in parts)])


async def check(
    db: Database, checks: list[tuple[Limit, str]], *, ip: str | None, user_id: object = None
) -> None:
    """Take one token from every bucket; raise if any is empty."""
    wait = 0.0
    async with db.system_transaction() as conn:
        for limit, bucket in checks:
            wait = max(
                wait,
                await store.take(
                    conn, bucket, capacity=limit.capacity, per_second=limit.per_second
                ),
            )
    if wait > 0:
        security_log.event(
            "rate_limited", ip=ip, user_id=user_id, limits=[limit.name for limit, _ in checks]
        )
        raise RateLimitedError(int(wait))


async def reset(db: Database, bucket: str) -> None:
    async with db.system_transaction() as conn:
        await store.reset(conn, bucket)

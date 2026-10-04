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
# Share links (ADR 0015): opening one, per IP; wrong PINs, per link; guest actions, per link.
SHARE_OPEN_IP = Limit("share-open-ip", capacity=20, per_second=1 / 30)
SHARE_PIN_LINK = Limit("share-pin-link", capacity=5, per_second=1 / 300)
SHARE_WRITE_LINK = Limit("share-write-link", capacity=120, per_second=1 / 2)
# Phone alerts (ADR 0018): registering devices and test alerts, per person.
PUSH_SUBSCRIBE = Limit("push-subscribe", capacity=10, per_second=1 / 600)
PUSH_TEST = Limit("push-test", capacity=5, per_second=1 / 120)
# Feed and sync keys (SECURITY.md §7.3): per key. Calendar apps poll every few minutes at
# most; a Shortcut syncs on a schedule or when Reminders closes.
FEED_KEY = Limit("feed-key", capacity=30, per_second=1 / 60)
SYNC_KEY = Limit("sync-key", capacity=60, per_second=1 / 10)
# Assigning chores, per person (each assignment alerts the assignee).
CHORE_ASSIGN = Limit("chore-assign", capacity=30, per_second=1 / 60)
# AI connector: app registration and the token endpoint per address; tool calls and changes
# per connection (A§12.4, S§7.7).
OAUTH_REGISTER_IP = Limit("oauth-register-ip", capacity=10, per_second=1 / 360)
OAUTH_TOKEN_IP = Limit("oauth-token-ip", capacity=30, per_second=1 / 10)
MCP_GRANT = Limit("mcp-grant", capacity=120, per_second=1)
MCP_WRITE_GRANT = Limit("mcp-write-grant", capacity=30, per_second=1 / 10)
# Wrong feed or sync keys, per address (only failures count).
KEY_FAIL_IP = Limit("key-fail-ip", capacity=10, per_second=1 / 60)
# Messages (ADR 0018): sending and starting conversations, per person.
MESSAGE_SEND = Limit("message-send", capacity=30, per_second=1 / 2)
CONVERSATION_START = Limit("conversation-start", capacity=20, per_second=1 / 60)


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

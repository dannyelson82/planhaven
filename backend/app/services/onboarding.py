"""The welcome tour and "What's new" (maintainer request, 2026-10-02): what each person has
seen, so each shows once per person rather than once per device."""

from dataclasses import dataclass
from datetime import datetime

from app import authz
from app.db import onboarding as store
from app.db.database import Database
from app.services.auth import CurrentSession


@dataclass(frozen=True, slots=True)
class State:
    welcome_done: bool
    whats_new_seen: str | None
    # When the account was made: someone who hasn't seen any "What's new" yet sees everything
    # released since then (cumulative).
    member_since: datetime | None = None


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


async def get(db: Database, session: CurrentSession) -> State:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        row = await store.get(conn, session.user.id)
        since = await store.member_since(conn, session.user.id)
    if row is None:
        return State(False, None, since)
    return State(row.welcome_done_at is not None, row.whats_new_seen, since)


async def update(
    db: Database, session: CurrentSession, *, welcome_done: bool, whats_new_seen: str | None
) -> State:
    """Marks the tour done and/or "What's new" seen up to a version (never back to an older
    one, e.g. from a device still running the previous version)."""
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        row = await store.get(conn, session.user.id)
        current = row.whats_new_seen if row else None
        if (
            whats_new_seen is not None
            and current is not None
            and _version(whats_new_seen) <= _version(current)
        ):
            whats_new_seen = None
        await store.put(conn, session.user.id, welcome_done=welcome_done, seen=whats_new_seen)
        row = await store.get(conn, session.user.id)
        since = await store.member_since(conn, session.user.id)
    if row is None:
        raise RuntimeError("onboarding row not written")
    return State(row.welcome_done_at is not None, row.whats_new_seen, since)

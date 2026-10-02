"""The calendar feed and iPhone Reminders sync (A§13.1, A§13.2, SECURITY.md §7.3).

Each person makes keys in Account (a fresh second factor first): one calendar feed link
(`phv_ics_`: read the feed, nothing else; regenerating replaces it) and a sync key per device
(`phv_sync_`: read the lists they chose for Reminders and tick their items, nothing else).
A key is shown once and stored as a hash; using one acts as its person, under RLS.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app import authz
from app.auth import tokens
from app.core import security_log
from app.db import asset_service as service_store
from app.db import auth as audit
from app.db import feeds as store
from app.db.database import Database
from app.services import asset_service, ics, limits
from app.services import lists as list_service
from app.services.auth import CurrentSession, user_from_row

TokenRow = store.TokenRow
PREFIX = {"ics": "phv_ics_", "sync": "phv_sync_"}
_SHAPE = {
    kind: re.compile(re.escape(prefix) + r"[A-Za-z0-9_-]{43}") for kind, prefix in PREFIX.items()
}
MAX_SYNC_KEYS = 10
MAX_PUSH = 500


class FeedError(ValueError):
    """A request that can't be done as asked (shown to the person)."""


@dataclass(frozen=True, slots=True)
class KeyHolder:
    """Who a feed or sync key acts for."""

    principal: authz.Principal
    token_id: uuid.UUID
    details: bool


async def authenticate(db: Database, kind: str, token: str, ip: str | None) -> KeyHolder | None:
    """A live key of this kind, or None. Rate limited per key; last use recorded."""
    # The shape of a real key (prefix + 43 URL-safe characters) before any database work.
    # Wrong, removed or malformed keys are security events (fail2ban/CrowdSec count them like
    # failed sign-ins). Well-formed wrong ones cost a lookup, so they're also limited per
    # address (failures only, so a household behind one address keeps working).
    if not _SHAPE[kind].fullmatch(token):
        security_log.event("key_failed", ip=ip, kind=kind, reason="malformed")
        return None
    async with db.system_transaction() as conn:
        row = await store.by_hash(conn, kind, tokens.token_hash(token))
        if row is not None:
            await store.used(conn, row.id, ip)
    if row is None:
        security_log.event("key_failed", ip=ip, kind=kind, reason="unknown")
        await limits.check(db, [(limits.KEY_FAIL_IP, limits.key(limits.KEY_FAIL_IP, ip))], ip=ip)
        return None
    limit = limits.FEED_KEY if kind == "ics" else limits.SYNC_KEY
    await limits.check(db, [(limit, limits.key(limit, row.id))], ip=ip, user_id=row.user_id)
    principal = authz.Principal(row.user_id, False, True, None, kind=kind)
    return KeyHolder(principal, row.id, row.details)


# ---------------------------------------------------------------- managing keys (Account)


@dataclass(frozen=True, slots=True)
class NewKey:
    row: TokenRow
    token: str  # shown once


async def keys(db: Database, session: CurrentSession) -> list[TokenRow]:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        return await store.own(conn, session.user.id)


async def make_key(
    db: Database,
    session: CurrentSession,
    *,
    kind: str,
    label: str,
    details: bool,
    ip: str | None,
) -> NewKey:
    authz.require(session.principal, authz.Action.TOKEN_CREATE)
    if kind not in PREFIX:
        raise FeedError("Unknown kind of key.")
    me = session.user.id
    token = tokens.new_token(PREFIX[kind])
    async with db.user_transaction(me) as conn:
        if kind == "sync" and sum(k.kind == "sync" for k in await store.own(conn, me)) >= (
            MAX_SYNC_KEYS
        ):
            raise FeedError("You have 10 sync keys already; remove one you don't use.")
        token_id = await store.create(
            conn,
            me,
            kind=kind,
            token_hash=tokens.token_hash(token),
            label=label.strip()[:80],
            details=details and kind == "ics",
        )
        await audit.record_audit(
            conn,
            action=f"token.{kind}.created",
            actor_user_id=me,
            ip=ip,
            resource_type="access_token",
            resource_id=token_id,
        )
        row = next(k for k in await store.own(conn, me) if k.id == token_id)
    return NewKey(row, token)


async def revoke_key(
    db: Database, session: CurrentSession, token_id: uuid.UUID, ip: str | None
) -> None:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        if not await store.revoke(conn, session.user.id, token_id):
            raise authz.NotFoundError("Not found.")
        await audit.record_audit(
            conn,
            action="token.revoked",
            actor_user_id=session.user.id,
            ip=ip,
            resource_type="access_token",
            resource_id=token_id,
        )


async def set_feed_details(db: Database, session: CurrentSession, details: bool) -> None:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        await store.set_details(conn, session.user.id, details)


# ---------------------------------------------------------------- the calendar feed


async def feed(db: Database, holder: KeyHolder, *, now: datetime | None = None) -> str:
    """The person's calendar: open tasks with due dates (theirs to do) and maintenance coming
    due. Titles only unless they chose to include notes."""
    authz.require(holder.principal, authz.Action.FEED_READ)
    me = holder.principal.user_id
    now = now or datetime.now(UTC)
    events: list[ics.Event] = []
    async with db.user_transaction(me) as conn:
        for t in await store.feed_tasks(conn, me):
            where = f" · {t.project_title}" if t.project_title else ""
            summary = f"{'Chore: ' if t.chore else ''}{t.title}{where}"
            start = t.due_at.astimezone(UTC).date() if t.due_all_day else t.due_at
            events.append(
                ics.Event(
                    uid=f"task-{t.id}@planhaven",
                    summary=summary,
                    start=start,
                    description=t.notes[:2000] if holder.details else "",
                    stamp=t.updated_at,
                )
            )
        for a in await store.feed_assets(conn):
            distance, hours = await service_store.highest(conn, a.id)
            lasts = await service_store.last_records(conn, a.id)
            for s in await service_store.schedules(conn, a.id):
                due = asset_service.due(
                    s, lasts.get(s.id), distance=distance, hours=hours, today=now.date()
                )
                if due.due_on is not None:
                    events.append(
                        ics.Event(
                            uid=f"service-{s.id}-{due.due_on:%Y%m%d}@planhaven",
                            summary=f"Service: {s.name} · {a.name}",
                            start=due.due_on,
                            description=s.notes[:2000] if holder.details else "",
                        )
                    )
    return ics.calendar("PlanHaven", events, now)


# ---------------------------------------------------------------- Reminders sync


@dataclass(frozen=True, slots=True)
class SyncList:
    list_id: uuid.UUID
    title: str
    reminders_name: str


async def synced_lists(db: Database, session: CurrentSession) -> list[SyncList]:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        rows = await store.synced_lists(conn, session.user.id)
    return [SyncList(r.list_id, r.title, r.reminders_name) for r in rows]


async def set_sync(
    db: Database, session: CurrentSession, list_id: uuid.UUID, reminders_name: str | None
) -> None:
    """Send this list to a Reminders list on your iPhone (or stop)."""
    authz.require(session.principal, authz.Action.USE_APP)
    name = reminders_name.strip()[:60] if reminders_name else None
    async with db.user_transaction(session.user.id) as conn:
        # Only lists the person can see (the database checks it too).
        await list_service.require_visible(conn, session, list_id)
        await store.set_sync(conn, session.user.id, list_id, name or None)


@dataclass(frozen=True, slots=True)
class SyncItem:
    id: uuid.UUID
    list: str  # the Reminders list's name
    title: str
    done: bool
    removed: bool


@dataclass(frozen=True, slots=True)
class Pull:
    cursor: str
    items: list[SyncItem]


def _title(text: str, quantity: Decimal | None, unit: str | None) -> str:
    if quantity is None:
        return text
    amount = f"{quantity.normalize():f}"
    return f"{text} ({amount}{' ' + unit if unit else ''})"


async def pull(
    db: Database, holder: KeyHolder, cursor: str | None, reminders: str | None = None
) -> Pull:
    """What changed in the synced lists since `cursor` (everything current without one);
    `reminders`: only the lists sent to that Reminders list (one block of the Shortcut)."""
    authz.require(holder.principal, authz.Action.SYNC_USE)
    since = None
    if cursor:
        try:
            since = datetime.fromisoformat(cursor)
        except ValueError:
            raise FeedError("Unknown cursor: sync again without one.") from None
    me = holder.principal.user_id
    async with db.user_transaction(me) as conn:
        rows = await store.sync_items(conn, me, since, reminders)
    newest = max((r.updated_at for r in rows), default=since or datetime.now(UTC))
    return Pull(
        newest.astimezone(UTC).isoformat(),
        [
            SyncItem(
                r.id, r.reminders_name, _title(r.text, r.quantity, r.unit), r.checked, r.deleted
            )
            for r in rows
        ],
    )


_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def ids_in(text: str) -> list[uuid.UUID]:
    """Item ids found in text (the Shortcut sends the ticked reminders' links), at most
    MAX_PUSH, in order, without repeats."""
    out: list[uuid.UUID] = []
    for match in _ID.findall(text.lower()):
        value = uuid.UUID(match)
        if value not in out:
            out.append(value)
        if len(out) >= MAX_PUSH:
            break
    return out


async def push(
    db: Database,
    holder: KeyHolder,
    *,
    done: list[uuid.UUID],
    undone: list[uuid.UUID],
    ip: str | None,
) -> int:
    """Items ticked (or unticked) on the phone. Only items in the person's synced lists; a
    tick is a state, not an edit, so it never conflicts (completion wins). Returns how many."""
    authz.require(holder.principal, authz.Action.SYNC_USE)
    if len(done) + len(undone) > MAX_PUSH:
        raise FeedError("Too many items at once.")
    me = holder.principal.user_id
    async with db.system_transaction() as conn:
        user_row = await audit.user_by_id(conn, me)
    if user_row is None:
        raise authz.NotFoundError("Not found.")
    # Ticking goes through the lists service as this person (its authz and RLS apply).
    acting = CurrentSession(holder.token_id, "", user_from_row(user_row), True)
    changed = 0
    for item_id, checked in [*((i, True) for i in done), *((i, False) for i in undone)]:
        async with db.user_transaction(me) as conn:
            if not await store.synced_item(conn, me, item_id):
                continue
        try:
            await list_service.update_item(
                db, acting, item_id, expected_version=None, fields={"checked": checked}, ip=ip
            )
            changed += 1
        except authz.AuthzError:
            continue  # e.g. only allowed to view that project
    return changed

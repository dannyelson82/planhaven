"""The change feed: what the iPhone app needs to keep an offline copy (ADR 0021, phase 0.5
milestone 3).

1. The app downloads a snapshot (`snapshot`), page by page. The first page carries the feed
   cursor to start from.
2. Then it asks for changes since its cursor (`since`): each says what changed (kind, id,
   upsert or delete) and, for an upsert, the item's current fields as the person sees them.
3. Access to a project, asset or contact gained or lost arrives as `access_gained` (take a
   snapshot of that scope) or `access_lost` (drop it).
4. Changes are kept 30 days; an older cursor gets `CursorExpiredError` (start over).

Who sees what is decided twice: the entries are limited to scopes the person belongs to now,
and the items are read as the person (RLS). Deleted items are only named, never shown.
"""

import base64
import binascii
import uuid
from dataclasses import dataclass, field
from typing import Any

from app import authz
from app.db import changes as store
from app.db.database import Database
from app.services.auth import CurrentSession

PAGE = 200


class CursorError(ValueError):
    """Not a cursor this server made."""


class CursorExpiredError(Exception):
    """The cursor is older than the 30 days of changes kept: take a new snapshot."""


def encode(txid: int, entry_id: int) -> str:
    return base64.urlsafe_b64encode(f"c1.{txid}.{entry_id}".encode()).decode().rstrip("=")


def decode(cursor: str) -> tuple[int, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        version, txid, entry_id = raw.split(".")
        if version != "c1":
            raise ValueError(version)
        return int(txid), int(entry_id)
    except ValueError, UnicodeDecodeError, binascii.Error:
        raise CursorError("Not a change cursor.") from None


@dataclass(frozen=True, slots=True)
class Change:
    kind: str
    id: uuid.UUID
    op: str
    project_id: uuid.UUID | None
    asset_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    data: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Changes:
    changes: list[Change]
    cursor: str
    more: bool


async def since(db: Database, session: CurrentSession, cursor: str, limit: int = PAGE) -> Changes:
    authz.require(session.principal, authz.Action.USE_APP)
    after = decode(cursor)
    limit = max(1, min(limit, PAGE))
    async with db.system_transaction() as conn:
        if after[0] <= await store.purged_through(conn):
            raise CursorExpiredError("Too old: take a new snapshot.")
        entries = await store.entries(conn, session.user.id, after, limit + 1)
    more = len(entries) > limit
    entries = entries[:limit]
    # The last word on each item in this page wins.
    latest: dict[tuple[str, uuid.UUID, str], store.Entry] = {}
    for e in entries:
        key = (e.kind, e.item_id, "access" if e.op.startswith("access") else "item")
        latest.pop(key, None)
        latest[key] = e
    wanted: dict[str, list[uuid.UUID]] = {}
    for e in latest.values():
        if e.op == "upsert":
            wanted.setdefault(e.kind, []).append(e.item_id)
    found: dict[str, dict[uuid.UUID, Any]] = {}
    async with db.user_transaction(session.user.id) as conn:
        for kind, ids in wanted.items():
            found[kind] = await store.rows(conn, kind, ids)
    out: list[Change] = []
    for e in latest.values():
        data = None
        if e.op == "upsert":
            data = found.get(e.kind, {}).get(e.item_id)
            if data is None:
                continue  # gone or not visible any more: a delete or access change follows
        out.append(Change(e.kind, e.item_id, e.op, e.project_id, e.asset_id, e.contact_id, data))
    next_cursor = encode(entries[-1].txid, entries[-1].id) if entries else cursor
    return Changes(out, next_cursor, more)


@dataclass(frozen=True, slots=True)
class Snapshot:
    items: list[Change] = field(default_factory=list)
    after: str | None = None  # the next page's position, None when done
    changes_cursor: str | None = None  # on the first page: where the feed starts


ZERO = uuid.UUID(int=0)


def _position(kind: str, item: uuid.UUID) -> str:
    return f"{kind}:{item}"


def _parse_position(after: str) -> tuple[int, uuid.UUID]:
    kind, _, item = after.partition(":")
    if kind not in store.KINDS:
        raise CursorError("Not a snapshot position.")
    try:
        return store.KINDS.index(kind), uuid.UUID(item)
    except ValueError:
        raise CursorError("Not a snapshot position.") from None


async def snapshot(
    db: Database,
    session: CurrentSession,
    *,
    after: str | None = None,
    scope: tuple[str, uuid.UUID] | None = None,
    limit: int = PAGE,
) -> Snapshot:
    """Everything the person can see now (or in one project, asset or contact), page by page,
    in a fixed order: by kind, then id. A position is "<kind>:<last id>"; the start of a kind
    is the all-zero id."""
    authz.require(session.principal, authz.Action.USE_APP)
    limit = max(1, min(limit, PAGE))
    start, start_id = (0, ZERO) if after is None else _parse_position(after)
    cursor = None
    if after is None:
        async with db.system_transaction() as conn:
            cursor = encode(await store.watermark(conn), 0)
    items: list[Change] = []
    position: str | None = None
    async with db.user_transaction(session.user.id) as conn:
        for index in range(start, len(store.KINDS)):
            kind = store.KINDS[index]
            room = limit - len(items)
            if room == 0:
                position = _position(kind, ZERO)
                break
            found = await store.page(
                conn, kind, start_id if index == start else ZERO, room + 1, scope
            )
            items.extend(_item(kind, item_id, data) for item_id, data in found[:room])
            if len(found) > room:
                position = _position(kind, items[-1].id)
                break
    return Snapshot(items, position, cursor)


def _item(kind: str, item_id: uuid.UUID, data: dict[str, Any]) -> Change:
    def scope_of(key: str) -> uuid.UUID | None:
        value = data.get(key)
        return uuid.UUID(value) if isinstance(value, str) else None

    project = item_id if kind == "projects" else scope_of("project_id")
    asset = item_id if kind == "assets" else scope_of("asset_id")
    contact = item_id if kind == "contacts" else scope_of("contact_id")
    return Change(kind, item_id, "upsert", project, asset, contact, data)

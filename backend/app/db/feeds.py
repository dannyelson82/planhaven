"""Queries for feed and sync keys, the calendar feed and Reminders sync (A§13.1, A§13.2).

Keys are looked up by hash in system context; everything a key then reads or changes runs as
its person (user transactions, RLS)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class TokenRow:
    id: uuid.UUID
    user_id: uuid.UUID
    kind: str
    label: str
    details: bool
    created_at: datetime
    last_used_at: datetime | None
    last_used_ip: str | None


async def by_hash(conn: AsyncConnection, kind: str, token_hash: bytes) -> TokenRow | None:
    """A live key of this kind, belonging to an enabled account (system context)."""
    row = (
        await conn.execute(
            text("""
                SELECT t.id, t.user_id, t.kind, t.label, t.details, t.created_at,
                       t.last_used_at, host(t.last_used_ip) AS last_used_ip
                FROM access_tokens t JOIN users u ON u.id = t.user_id AND u.disabled_at IS NULL
                WHERE t.token_hash = :h AND t.kind = :k AND t.revoked_at IS NULL
            """),
            {"h": token_hash, "k": kind},
        )
    ).first()
    return TokenRow(**row._mapping) if row else None


async def used(conn: AsyncConnection, token_id: uuid.UUID, ip: str | None) -> None:
    """Last use, at most once a minute (system context)."""
    await conn.execute(
        text("""
            UPDATE access_tokens SET last_used_at = now(), last_used_ip = CAST(:ip AS inet)
            WHERE id = :id AND (last_used_at IS NULL OR last_used_at < now() - interval '1 minute')
        """),
        {"id": token_id, "ip": ip},
    )


async def own(conn: AsyncConnection, user_id: uuid.UUID) -> list[TokenRow]:
    rows = await conn.execute(
        text("""
            SELECT id, user_id, kind, label, details, created_at, last_used_at,
                   host(last_used_ip) AS last_used_ip
            FROM access_tokens WHERE user_id = :u AND revoked_at IS NULL
            ORDER BY created_at LIMIT 50
        """),
        {"u": user_id},
    )
    return [TokenRow(**r._mapping) for r in rows]


async def create(
    conn: AsyncConnection,
    user_id: uuid.UUID,
    *,
    kind: str,
    token_hash: bytes,
    label: str,
    details: bool,
) -> uuid.UUID:
    if kind == "ics":  # one feed per person: a new one replaces the old link
        await conn.execute(
            text("""
                UPDATE access_tokens SET revoked_at = now()
                WHERE user_id = :u AND kind = 'ics' AND revoked_at IS NULL
            """),
            {"u": user_id},
        )
    token_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO access_tokens (id, user_id, kind, token_hash, label, details)
            VALUES (:id, :u, :k, :h, :l, :d)
        """),
        {"id": token_id, "u": user_id, "k": kind, "h": token_hash, "l": label, "d": details},
    )
    return token_id


async def revoke(conn: AsyncConnection, user_id: uuid.UUID, token_id: uuid.UUID) -> bool:
    result = await conn.execute(
        text("""
            UPDATE access_tokens SET revoked_at = now()
            WHERE id = :id AND user_id = :u AND revoked_at IS NULL
        """),
        {"id": token_id, "u": user_id},
    )
    return result.rowcount == 1


async def set_details(conn: AsyncConnection, user_id: uuid.UUID, details: bool) -> None:
    await conn.execute(
        text("""
            UPDATE access_tokens SET details = :d
            WHERE user_id = :u AND kind = 'ics' AND revoked_at IS NULL
        """),
        {"u": user_id, "d": details},
    )


# ---------------------------------------------------------------- the calendar feed


@dataclass(frozen=True, slots=True)
class FeedTaskRow:
    id: uuid.UUID
    title: str
    notes: str
    due_at: datetime
    due_all_day: bool
    updated_at: datetime
    project_title: str | None
    chore: bool


async def feed_tasks(conn: AsyncConnection, me: uuid.UUID) -> list[FeedTaskRow]:
    """Open tasks with a due date from a month ago to a year ahead: chores assigned to this
    person, and unassigned tasks in projects they can change (RLS: only what they can see)."""
    rows = await conn.execute(
        text("""
            SELECT t.id, t.title, t.notes, t.due_at, t.due_all_day, t.updated_at,
                   p.title AS project_title, t.assignee_id IS NOT NULL AS chore
            FROM tasks t
            LEFT JOIN projects p ON p.id = t.project_id AND p.deleted_at IS NULL
            WHERE t.deleted_at IS NULL AND t.done_at IS NULL AND t.due_at IS NOT NULL
              AND t.due_at BETWEEN now() - interval '30 days' AND now() + interval '400 days'
              AND (t.assignee_id = :me
                   OR (t.assignee_id IS NULL AND app.project_role(t.project_id)
                       IN ('owner', 'editor')))
            ORDER BY t.due_at LIMIT 2000
        """),
        {"me": me},
    )
    return [FeedTaskRow(**r._mapping) for r in rows]


@dataclass(frozen=True, slots=True)
class FeedAssetRow:
    id: uuid.UUID
    name: str


async def feed_assets(conn: AsyncConnection) -> list[FeedAssetRow]:
    """Assets this person can see that have maintenance schedules (RLS)."""
    rows = await conn.execute(
        text("""
            SELECT DISTINCT a.id, a.name FROM assets a
            JOIN service_schedules s ON s.asset_id = a.id AND s.deleted_at IS NULL
            WHERE a.deleted_at IS NULL AND app.asset_role(a.id) IS NOT NULL LIMIT 500
        """)
    )
    return [FeedAssetRow(**r._mapping) for r in rows]


# ---------------------------------------------------------------- Reminders sync


@dataclass(frozen=True, slots=True)
class SyncListRow:
    list_id: uuid.UUID
    reminders_name: str
    title: str


async def synced_lists(conn: AsyncConnection, me: uuid.UUID) -> list[SyncListRow]:
    rows = await conn.execute(
        text("""
            SELECT s.list_id, s.reminders_name, l.title
            FROM list_sync s JOIN lists l ON l.id = s.list_id AND l.deleted_at IS NULL
            WHERE s.user_id = :me ORDER BY s.reminders_name, l.title
        """),
        {"me": me},
    )
    return [SyncListRow(**r._mapping) for r in rows]


async def set_sync(
    conn: AsyncConnection, me: uuid.UUID, list_id: uuid.UUID, reminders_name: str | None
) -> None:
    if reminders_name is None:
        await conn.execute(
            text("DELETE FROM list_sync WHERE user_id = :me AND list_id = :l"),
            {"me": me, "l": list_id},
        )
        return
    await conn.execute(
        text("""
            INSERT INTO list_sync (user_id, list_id, reminders_name) VALUES (:me, :l, :n)
            ON CONFLICT (user_id, list_id) DO UPDATE SET reminders_name = EXCLUDED.reminders_name
        """),
        {"me": me, "l": list_id, "n": reminders_name},
    )


@dataclass(frozen=True, slots=True)
class SyncItemRow:
    id: uuid.UUID
    reminders_name: str
    text: str
    quantity: Decimal | None
    unit: str | None
    checked: bool
    deleted: bool
    updated_at: datetime


async def sync_items(
    conn: AsyncConnection, me: uuid.UUID, since: datetime | None, reminders: str | None = None
) -> list[SyncItemRow]:
    """Items of this person's synced lists: all current ones, or (with `since`) everything
    changed after it, deleted ones included so the phone can remove them."""
    rows = await conn.execute(
        text("""
            SELECT i.id, s.reminders_name, i.text, i.quantity, i.unit,
                   i.checked_at IS NOT NULL AS checked,
                   (i.deleted_at IS NOT NULL OR l.deleted_at IS NOT NULL) AS deleted,
                   greatest(i.updated_at, s.created_at) AS updated_at
            FROM list_sync s
            JOIN lists l ON l.id = s.list_id
            JOIN list_items i ON i.list_id = s.list_id
            WHERE s.user_id = :me
              AND (CAST(:list AS text) IS NULL OR s.reminders_name = :list)
              AND (CAST(:since AS timestamptz) IS NULL
                   AND i.deleted_at IS NULL AND l.deleted_at IS NULL
                   OR greatest(i.updated_at, s.created_at) > :since)
            ORDER BY greatest(i.updated_at, s.created_at), i.id LIMIT 2000
        """),
        {"me": me, "since": since, "list": reminders},
    )
    return [SyncItemRow(**r._mapping) for r in rows]


async def synced_item(conn: AsyncConnection, me: uuid.UUID, item_id: uuid.UUID) -> bool:
    """Is this item in one of the person's synced lists? (What a sync key may tick.)"""
    found = await conn.scalar(
        text("""
            SELECT 1 FROM list_items i JOIN list_sync s ON s.list_id = i.list_id
            WHERE i.id = :i AND s.user_id = :me AND i.deleted_at IS NULL
        """),
        {"i": item_id, "me": me},
    )
    return found is not None

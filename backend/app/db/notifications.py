"""Queries for notifications, notification settings and push subscriptions (ADR 0018).

People read and change only their own (RLS); the worker reads them in system context to send
phone alerts and to find tasks and services that are due.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class NotificationRow:
    id: uuid.UUID
    user_id: uuid.UUID
    kind: str
    data: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


async def notify(
    conn: AsyncConnection,
    user_id: uuid.UUID,
    kind: str,
    data: dict[str, Any],
    dedupe_key: str | None = None,
) -> bool:
    """Add a notification; with a dedupe key, only once per person and key. True if added."""
    result = await conn.execute(
        text("""
            INSERT INTO notifications (user_id, kind, data, dedupe_key)
            VALUES (:u, :k, CAST(:d AS jsonb), :key)
            ON CONFLICT (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
        """),
        {"u": user_id, "k": kind, "d": json.dumps(data), "key": dedupe_key},
    )
    return result.rowcount == 1


async def own(
    conn: AsyncConnection, user_id: uuid.UUID, kinds: list[str], limit: int
) -> list[NotificationRow]:
    rows = await conn.execute(
        text("""
            SELECT id, user_id, kind, data, created_at, read_at FROM notifications
            WHERE user_id = :u AND kind = ANY(:kinds)
            ORDER BY created_at DESC LIMIT :n
        """),
        {"u": user_id, "kinds": kinds, "n": limit},
    )
    return [NotificationRow(**r._mapping) for r in rows]


async def unread_count(conn: AsyncConnection, user_id: uuid.UUID, kinds: list[str]) -> int:
    n = await conn.scalar(
        text("""
            SELECT count(*) FROM (
                SELECT 1 FROM notifications
                WHERE user_id = :u AND read_at IS NULL AND kind = ANY(:kinds) LIMIT 100
            ) unread
        """),
        {"u": user_id, "kinds": kinds},
    )
    return int(n or 0)


async def mark_all_read(conn: AsyncConnection, user_id: uuid.UUID) -> None:
    await conn.execute(
        text("UPDATE notifications SET read_at = now() WHERE user_id = :u AND read_at IS NULL"),
        {"u": user_id},
    )


# ---------------------------------------------------------------- settings


@dataclass(frozen=True, slots=True)
class SettingsRow:
    user_id: uuid.UUID
    prefs: dict[str, str]
    quiet_from: time | None
    quiet_to: time | None
    time_zone: str
    previews: bool


async def get_settings(conn: AsyncConnection, user_id: uuid.UUID) -> SettingsRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT user_id, prefs, quiet_from, quiet_to, time_zone, previews
                FROM notification_settings WHERE user_id = :u
            """),
            {"u": user_id},
        )
    ).first()
    return SettingsRow(**row._mapping) if row else None


async def put_settings(
    conn: AsyncConnection,
    user_id: uuid.UUID,
    *,
    prefs: dict[str, str],
    quiet_from: time | None,
    quiet_to: time | None,
    time_zone: str,
    previews: bool,
) -> None:
    await conn.execute(
        text("""
            INSERT INTO notification_settings
                (user_id, prefs, quiet_from, quiet_to, time_zone, previews)
            VALUES (:u, CAST(:p AS jsonb), :qf, :qt, :tz, :pv)
            ON CONFLICT (user_id) DO UPDATE SET
                prefs = EXCLUDED.prefs, quiet_from = EXCLUDED.quiet_from,
                quiet_to = EXCLUDED.quiet_to, time_zone = EXCLUDED.time_zone,
                previews = EXCLUDED.previews, updated_at = now()
        """),
        {
            "u": user_id,
            "p": json.dumps(prefs),
            "qf": quiet_from,
            "qt": quiet_to,
            "tz": time_zone,
            "pv": previews,
        },
    )


# ---------------------------------------------------------------- push subscriptions


@dataclass(frozen=True, slots=True)
class SubscriptionRow:
    id: uuid.UUID
    user_id: uuid.UUID
    endpoint: str
    p256dh: str
    auth: str
    label: str
    created_at: datetime
    last_success_at: datetime | None


async def subscriptions(conn: AsyncConnection, user_id: uuid.UUID) -> list[SubscriptionRow]:
    rows = await conn.execute(
        text("""
            SELECT id, user_id, endpoint, p256dh, auth, label, created_at, last_success_at
            FROM push_subscriptions WHERE user_id = :u ORDER BY created_at LIMIT 50
        """),
        {"u": user_id},
    )
    return [SubscriptionRow(**r._mapping) for r in rows]


async def add_subscription(
    conn: AsyncConnection,
    user_id: uuid.UUID,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    label: str,
) -> uuid.UUID:
    """Register this browser for the user; the same browser's earlier registration (by them
    or by someone who used it before) is replaced."""
    await conn.execute(text("SELECT app.release_push_endpoint(:e)"), {"e": endpoint})
    await conn.execute(
        text("DELETE FROM push_subscriptions WHERE user_id = :u AND endpoint = :e"),
        {"u": user_id, "e": endpoint},
    )
    sub_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth, label)
            VALUES (:id, :u, :e, :p, :a, :l)
        """),
        {"id": sub_id, "u": user_id, "e": endpoint, "p": p256dh, "a": auth, "l": label},
    )
    return sub_id


async def count_subscriptions(conn: AsyncConnection, user_id: uuid.UUID) -> int:
    n = await conn.scalar(
        text("SELECT count(*) FROM push_subscriptions WHERE user_id = :u"), {"u": user_id}
    )
    return int(n or 0)


async def delete_subscription(conn: AsyncConnection, user_id: uuid.UUID, sub_id: uuid.UUID) -> bool:
    result = await conn.execute(
        text("DELETE FROM push_subscriptions WHERE id = :id AND user_id = :u"),
        {"id": sub_id, "u": user_id},
    )
    return result.rowcount == 1


async def delete_endpoint(conn: AsyncConnection, user_id: uuid.UUID, endpoint: str) -> None:
    await conn.execute(
        text("DELETE FROM push_subscriptions WHERE user_id = :u AND endpoint = :e"),
        {"u": user_id, "e": endpoint},
    )


# ---------------------------------------------------------------- sending (system context)


@dataclass(frozen=True, slots=True)
class PendingRow:
    id: uuid.UUID
    user_id: uuid.UUID
    kind: str
    data: dict[str, Any]
    push_attempts: int
    read: bool


async def claim_pending(conn: AsyncConnection, limit: int) -> list[PendingRow]:
    """Notifications due to be pushed, leased for 5 minutes so another worker skips them."""
    rows = await conn.execute(
        text("""
            UPDATE notifications SET push_after = now() + interval '5 minutes',
                                     push_attempts = push_attempts + 1
            WHERE id IN (
                SELECT id FROM notifications
                WHERE push_state = 'pending' AND push_after <= now()
                ORDER BY push_after LIMIT :n FOR UPDATE SKIP LOCKED
            )
            RETURNING id, user_id, kind, data, push_attempts, read_at IS NOT NULL AS read
        """),
        {"n": limit},
    )
    return [PendingRow(**r._mapping) for r in rows]


async def set_push_state(
    conn: AsyncConnection, notification_id: uuid.UUID, state: str, after: datetime | None = None
) -> None:
    await conn.execute(
        text("""
            UPDATE notifications SET push_state = :s, push_after = coalesce(:a, push_after)
            WHERE id = :id
        """),
        {"id": notification_id, "s": state, "a": after},
    )


async def subscription_result(conn: AsyncConnection, sub_id: uuid.UUID, ok: bool) -> None:
    if ok:
        await conn.execute(
            text(
                "UPDATE push_subscriptions SET last_success_at = now(), failures = 0 WHERE id = :id"
            ),
            {"id": sub_id},
        )
    else:
        # A device that keeps failing (two weeks of daily reminders) is dropped.
        await conn.execute(
            text("UPDATE push_subscriptions SET failures = failures + 1 WHERE id = :id"),
            {"id": sub_id},
        )
        await conn.execute(
            text("DELETE FROM push_subscriptions WHERE id = :id AND failures >= 15"),
            {"id": sub_id},
        )


async def forget_subscription(conn: AsyncConnection, sub_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM push_subscriptions WHERE id = :id"), {"id": sub_id})


# ---------------------------------------------------------------- reminders (system context)


@dataclass(frozen=True, slots=True)
class DueTaskRow:
    task_id: uuid.UUID
    title: str
    project_id: uuid.UUID
    project_title: str
    due_at: datetime
    due_all_day: bool
    user_id: uuid.UUID


async def tasks_due_around_now(conn: AsyncConnection) -> list[DueTaskRow]:
    """Open tasks due from four days ago to two days ahead, with who to tell: the project's
    owners and editors. Assigned tasks are chores, with their own reminders
    (app.services.chores)."""
    rows = await conn.execute(
        text("""
            SELECT t.id AS task_id, t.title, t.project_id, p.title AS project_title,
                   t.due_at, t.due_all_day, m.user_id
            FROM tasks t
            JOIN projects p ON p.id = t.project_id AND p.deleted_at IS NULL
                           AND p.stage <> 'archived'
            JOIN project_members m ON m.project_id = t.project_id
                AND t.assignee_id IS NULL AND m.role IN ('owner', 'editor')
            JOIN users u ON u.id = m.user_id AND u.disabled_at IS NULL
            WHERE t.deleted_at IS NULL AND t.done_at IS NULL AND t.due_at IS NOT NULL
              AND t.due_at BETWEEN now() - interval '4 days' AND now() + interval '2 days'
            LIMIT 5000
        """)
    )
    return [DueTaskRow(**r._mapping) for r in rows]


@dataclass(frozen=True, slots=True)
class ServiceAssetRow:
    asset_id: uuid.UUID
    asset_name: str


async def assets_with_schedules(conn: AsyncConnection) -> list[ServiceAssetRow]:
    rows = await conn.execute(
        text("""
            SELECT DISTINCT a.id AS asset_id, a.name AS asset_name
            FROM assets a JOIN service_schedules s ON s.asset_id = a.id AND s.deleted_at IS NULL
            WHERE a.deleted_at IS NULL LIMIT 2000
        """)
    )
    return [ServiceAssetRow(**r._mapping) for r in rows]


async def asset_editors(conn: AsyncConnection, asset_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await conn.execute(
        text("""
            SELECT m.user_id FROM asset_members m
            JOIN users u ON u.id = m.user_id AND u.disabled_at IS NULL
            WHERE m.asset_id = :a AND m.role IN ('owner', 'editor')
        """),
        {"a": asset_id},
    )
    return [r.user_id for r in rows]


async def settings_for(conn: AsyncConnection, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Each person's time zone (system context)."""
    rows = await conn.execute(
        text("SELECT user_id, time_zone FROM notification_settings WHERE user_id = ANY(:u)"),
        {"u": user_ids},
    )
    return {r.user_id: r.time_zone for r in rows}

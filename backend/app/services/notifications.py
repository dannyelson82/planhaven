"""Notifications: the in-app list, each person's settings, phone alerts (Web Push) and the
reminders that create them (ADR 0018, A§13.3, A§15, SECURITY.md §7.12).

Notifications carry metadata only (names and titles): never note bodies, message text beyond
an opt-out preview, codes or tokens. Each kind belongs to a group the person can set to "on
the phone" (also in the app), "in the app" or "off"; security notices can't be turned off.
"""

import asyncio
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import authz
from app.db import admin as admin_store
from app.db import asset_service as service_store
from app.db import notifications as store
from app.db.database import Database
from app.push import webpush
from app.services import asset_service, limits
from app.services.auth import CurrentSession

# group -> the kinds in it, and its label in Account.
GROUPS: dict[str, tuple[str, ...]] = {
    "shared": (
        "shared_with_you",
        "asset_shared_with_you",
        "contact_shared_with_you",
        "template_shared_with_you",
    ),
    "tasks": ("task_due", "task_overdue"),
    "service": ("service_due", "service_overdue"),
    "share_links": ("share_link_used",),
    "messages": ("message",),
    "security": ("new_sign_in", "security_change", "push_test"),
}
GROUP_OF = {kind: group for group, kinds in GROUPS.items() for kind in kinds}
CHOICES = ("push", "app", "off")
DEFAULT_CHOICE = "push"
MAX_DEVICES = 10
Sender = webpush.Sender
LIST_LIMIT = 100


class SettingsError(ValueError):
    """Settings that can't be saved as given."""


# ---------------------------------------------------------------- wording


@dataclass(frozen=True, slots=True)
class Text:
    title: str
    body: str
    url: str


_SECURITY_CHANGES = {
    "password_changed": "Your password was changed",  # nosec B105: message text
    "password_reset": "Your password was reset with a link",  # nosec B105: message text
    "authenticator_added": "An authenticator app was added to your account",
    "passkey_added": "A passkey was added to your account",
    "second_factor_reset": "An admin reset your second factor",
    "admin_granted": "You were made an admin",
    "admin_revoked": "You're no longer an admin",
}


def _s(data: dict[str, Any], key: str, limit: int = 120) -> str:
    value = data.get(key)
    return str(value)[:limit] if value is not None else ""


# Shared with you: (what it is, the id field, the app path).
_SHARED = {
    "shared_with_you": ("A project", "project_id", "/projects"),
    "asset_shared_with_you": ("An asset", "asset_id", "/assets"),
    "contact_shared_with_you": ("A contact", "contact_id", "/contacts"),
    "template_shared_with_you": ("A template", "template_id", "/templates"),
}
_CHECK = "If this wasn't you, change your password."


def render(kind: str, data: dict[str, Any], previews: bool = True) -> Text:
    """What a notification says, and where tapping it goes (an app path, never a full URL).
    `previews`: the person's choice to see the start of messages in notifications."""
    title = _s(data, "title")
    project = f"/projects/{_s(data, 'project_id')}"
    asset = f"/assets/{_s(data, 'asset_id')}"
    if kind in _SHARED:
        what, field, base = _SHARED[kind]
        by = _s(data, "by", 80) or "Someone"
        return Text(f"{by} shared “{title}” with you", what, f"{base}/{_s(data, field)}")
    match kind:
        case "task_due":
            return Text(f"Due today: {title}", _s(data, "project_title"), project)
        case "task_overdue":
            return Text(f"Overdue: {title}", _s(data, "project_title"), project)
        case "service_due":
            return Text(f"Due soon: {title}", _s(data, "asset_name"), asset)
        case "service_overdue":
            return Text(f"Overdue: {title}", _s(data, "asset_name"), asset)
        case "share_link_used":
            guest = _s(data, "guest", 60) or "A guest"
            link = _s(data, "link_name", 80)
            return Text(
                f"{guest} used your share link “{link}”",
                _s(data, "project_title"),
                f"{project}/links",
            )
        case "message":
            sender = _s(data, "from", 80) or "Someone"
            group = _s(data, "group", 100)
            preview = _s(data, "preview", 100) if previews else ""
            return Text(
                f"{sender} in {group}" if group else f"Message from {sender}",
                preview or "New message",
                f"/messages/{_s(data, 'conversation_id')}",
            )
        case "new_sign_in":
            return Text("New sign-in to your account", _CHECK, "/account")
        case "security_change":
            change = _SECURITY_CHANGES.get(_s(data, "change"), "Your account security changed")
            return Text(change, _CHECK, "/account")
        case "push_test":
            return Text("Phone alerts work", "PlanHaven can reach this device.", "/notifications")
        case _:
            return Text("Something changed", "", "/notifications")


# ---------------------------------------------------------------- settings


@dataclass(frozen=True, slots=True)
class Settings:
    prefs: dict[str, str]  # group -> push | app | off (every group present)
    quiet_from: time | None
    quiet_to: time | None
    time_zone: str
    previews: bool


def _complete(prefs: dict[str, str]) -> dict[str, str]:
    out = {g: prefs.get(g, DEFAULT_CHOICE) for g in GROUPS}
    if out["security"] == "off":
        out["security"] = "app"
    return out


def _settings(row: store.SettingsRow | None) -> Settings:
    if row is None:
        return Settings(_complete({}), None, None, "UTC", True)
    return Settings(_complete(row.prefs), row.quiet_from, row.quiet_to, row.time_zone, row.previews)


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        return ZoneInfo("UTC")


def _shown_kinds(settings: Settings) -> list[str]:
    return [k for g, kinds in GROUPS.items() if settings.prefs[g] != "off" for k in kinds]


async def get_settings(db: Database, session: CurrentSession) -> Settings:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        return _settings(await store.get_settings(conn, session.user.id))


async def put_settings(
    db: Database,
    session: CurrentSession,
    *,
    prefs: dict[str, str],
    quiet_from: time | None,
    quiet_to: time | None,
    time_zone: str,
    previews: bool,
) -> Settings:
    authz.require(session.principal, authz.Action.USE_APP)
    if set(prefs) - set(GROUPS) or set(prefs.values()) - set(CHOICES):
        raise SettingsError("Unknown notification setting.")
    if prefs.get("security") == "off":
        raise SettingsError("Security notices can't be turned off.")
    if (quiet_from is None) != (quiet_to is None):
        raise SettingsError("Give both the start and the end of quiet hours.")
    try:
        ZoneInfo(time_zone)
    except ZoneInfoNotFoundError, ValueError:
        raise SettingsError("Unknown time zone.") from None
    async with db.user_transaction(session.user.id) as conn:
        await store.put_settings(
            conn,
            session.user.id,
            prefs=_complete(prefs),
            quiet_from=quiet_from,
            quiet_to=quiet_to,
            time_zone=time_zone,
            previews=previews,
        )
        return _settings(await store.get_settings(conn, session.user.id))


# ---------------------------------------------------------------- the list


@dataclass(frozen=True, slots=True)
class Notification:
    id: uuid.UUID
    kind: str
    data: dict[str, Any]
    text: Text
    created_at: datetime
    read: bool


async def list_own(db: Database, session: CurrentSession) -> list[Notification]:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        settings = _settings(await store.get_settings(conn, session.user.id))
        rows = await store.own(conn, session.user.id, _shown_kinds(settings), LIST_LIMIT)
    return [
        Notification(
            r.id,
            r.kind,
            r.data,
            render(r.kind, r.data, settings.previews),
            r.created_at,
            r.read_at is not None,
        )
        for r in rows
    ]


async def unread(db: Database, session: CurrentSession) -> int:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        settings = _settings(await store.get_settings(conn, session.user.id))
        return await store.unread_count(conn, session.user.id, _shown_kinds(settings))


async def mark_read(db: Database, session: CurrentSession, notification_id: uuid.UUID) -> bool:
    async with db.user_transaction(session.user.id) as conn:
        return await admin_store.mark_read(conn, session.user.id, notification_id)


async def mark_all_read(db: Database, session: CurrentSession) -> None:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        await store.mark_all_read(conn, session.user.id)


# ---------------------------------------------------------------- devices


Device = store.SubscriptionRow


async def devices(db: Database, session: CurrentSession) -> list[Device]:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        return await store.subscriptions(conn, session.user.id)


async def add_device(
    db: Database,
    session: CurrentSession,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    label: str,
    ip: str | None,
) -> uuid.UUID:
    """Turn on phone alerts for this browser. Only known push services are accepted, since
    the server will send requests to this address (SSRF, SECURITY.md §7.8)."""
    authz.require(session.principal, authz.Action.USE_APP)
    if not webpush.endpoint_allowed(endpoint):
        raise SettingsError("This browser's push service isn't supported.")
    if not webpush.keys_valid(p256dh, auth):
        raise SettingsError("This browser sent invalid push keys.")
    await limits.check(
        db,
        [(limits.PUSH_SUBSCRIBE, limits.key(limits.PUSH_SUBSCRIBE, session.user.id))],
        ip=ip,
        user_id=session.user.id,
    )
    async with db.user_transaction(session.user.id) as conn:
        if await store.count_subscriptions(conn, session.user.id) >= MAX_DEVICES:
            await _drop_oldest(conn, session.user.id)
        return await store.add_subscription(
            conn, session.user.id, endpoint=endpoint, p256dh=p256dh, auth=auth, label=label
        )


async def _drop_oldest(conn: Any, user_id: uuid.UUID) -> None:
    subs = await store.subscriptions(conn, user_id)
    if subs:
        await store.delete_subscription(conn, user_id, subs[0].id)


async def remove_device(db: Database, session: CurrentSession, device_id: uuid.UUID) -> bool:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        return await store.delete_subscription(conn, session.user.id, device_id)


async def forget_this_browser(db: Database, session: CurrentSession, endpoint: str) -> None:
    """On sign-out: this browser stops getting this person's alerts."""
    async with db.user_transaction(session.user.id) as conn:
        await store.delete_endpoint(conn, session.user.id, endpoint[:1000])


async def send_test(db: Database, session: CurrentSession, ip: str | None) -> None:
    authz.require(session.principal, authz.Action.USE_APP)
    await limits.check(
        db,
        [(limits.PUSH_TEST, limits.key(limits.PUSH_TEST, session.user.id))],
        ip=ip,
        user_id=session.user.id,
    )
    async with db.user_transaction(session.user.id) as conn:
        await store.notify(conn, session.user.id, "push_test", {})


# ---------------------------------------------------------------- sending (the worker)


def in_quiet_hours(settings: Settings, now: datetime) -> datetime | None:
    """When quiet hours end, if `now` is inside them (in the person's time zone)."""
    if settings.quiet_from is None or settings.quiet_to is None:
        return None
    local = now.astimezone(zone(settings.time_zone))
    start, end, at = settings.quiet_from, settings.quiet_to, local.timetz().replace(tzinfo=None)
    inside = (start <= at < end) if start < end else (at >= start or at < end)
    if not inside or start == end:
        return None
    end_day = local.date() if at < end else local.date() + timedelta(days=1)
    return datetime.combine(end_day, end, tzinfo=local.tzinfo).astimezone(UTC)


def payload(kind: str, data: dict[str, Any], previews: bool = True) -> bytes:
    text = render(kind, data, previews)
    return json.dumps(
        {"title": text.title[:120], "body": text.body[:200], "url": text.url[:300]}
    ).encode()


class PushSender(Protocol):
    def send(self, target: webpush.Target, payload: bytes) -> int: ...


async def dispatch(db: Database, sender: PushSender, *, batch: int = 20) -> int:
    """Send pending phone alerts (system context). Returns how many were handled."""
    async with db.system_transaction() as conn:
        pending = await store.claim_pending(conn, batch)
    now = datetime.now(UTC)
    for n in pending:
        async with db.system_transaction() as conn:
            settings = _settings(await store.get_settings(conn, n.user_id))
            subs = await store.subscriptions(conn, n.user_id)
        group = GROUP_OF.get(n.kind, "security")
        if settings.prefs[group] != "push" or not subs or n.read:  # read in the app already
            async with db.system_transaction() as conn:
                await store.set_push_state(conn, n.id, "skipped")
            continue
        quiet_until = in_quiet_hours(settings, now)
        if quiet_until is not None and n.kind != "push_test":
            async with db.system_transaction() as conn:
                await store.set_push_state(conn, n.id, "pending", quiet_until)
            continue
        body = payload(n.kind, n.data, settings.previews)
        delivered = False
        for sub in subs:
            target = webpush.Target(sub.endpoint, sub.p256dh, sub.auth)
            try:
                status = await asyncio.to_thread(sender.send, target, body)
            except webpush.PushError:
                async with db.system_transaction() as conn:
                    await store.subscription_result(conn, sub.id, ok=False)
                continue
            async with db.system_transaction() as conn:
                if status in (404, 410):
                    await store.forget_subscription(conn, sub.id)
                else:
                    await store.subscription_result(conn, sub.id, ok=True)
                    delivered = True
        state = "sent" if delivered else ("failed" if n.push_attempts >= 3 else "pending")
        async with db.system_transaction() as conn:
            await store.set_push_state(
                conn, n.id, state, now + timedelta(minutes=10 * n.push_attempts)
            )
    return len(pending)


# ---------------------------------------------------------------- reminders (the worker)


def _due_date(due_at: datetime, all_day: bool, tz: ZoneInfo) -> date:
    # An all-day due date is stored as midnight UTC of that day.
    return due_at.astimezone(UTC).date() if all_day else due_at.astimezone(tz).date()


async def remind(db: Database, *, now: datetime | None = None) -> int:
    """Hourly: tasks due today or overdue (up to three days), services due soon or overdue.
    Each reminder is sent once (dedupe keys). Returns how many were added."""
    now = now or datetime.now(UTC)
    added = 0
    async with db.system_transaction() as conn:
        tasks = await store.tasks_due_around_now(conn)
        zones = await store.settings_for(conn, list({t.user_id for t in tasks}))
        for t in tasks:
            tz = zone(zones.get(t.user_id, "UTC"))
            today = now.astimezone(tz).date()
            due = _due_date(t.due_at, t.due_all_day, tz)
            data = {
                "title": t.title[:120],
                "project_id": str(t.project_id),
                "project_title": t.project_title[:120],
                "task_id": str(t.task_id),
            }
            if due == today:
                added += await store.notify(
                    conn, t.user_id, "task_due", data, f"task_due:{t.task_id}:{due}"
                )
            elif today - timedelta(days=3) <= due < today:
                added += await store.notify(
                    conn, t.user_id, "task_overdue", data, f"task_overdue:{t.task_id}:{due}"
                )
        for a in await store.assets_with_schedules(conn):
            added += await _remind_services(conn, a, now)
    return added


async def _remind_services(conn: Any, asset: store.ServiceAssetRow, now: datetime) -> int:
    distance, hours = await service_store.highest(conn, asset.asset_id)
    lasts = await service_store.last_records(conn, asset.asset_id)
    people: Iterable[uuid.UUID] | None = None
    added = 0
    for s in await service_store.schedules(conn, asset.asset_id):
        last = lasts.get(s.id)
        due = asset_service.due(s, last, distance=distance, hours=hours, today=now.date())
        if due.status not in ("soon", "overdue"):
            continue
        if people is None:
            people = await store.asset_editors(conn, asset.asset_id)
        kind = "service_overdue" if due.status == "overdue" else "service_due"
        data = {
            "title": s.name[:120],
            "asset_id": str(asset.asset_id),
            "asset_name": asset.asset_name[:120],
        }
        key = f"{kind}:{s.id}:{last.id if last else 'never'}"
        for user_id in people:
            added += await store.notify(conn, user_id, kind, data, key)
    return added

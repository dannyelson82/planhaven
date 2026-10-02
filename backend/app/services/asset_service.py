"""Keeping an asset serviced: meter readings, maintenance schedules from the manufacturer
("oil every 8,000 km or 12 months, whichever first") and service records (maintainer's
testing notes, 2026-10-02).

The asset's members see all of it; its owners and editors change it (ASSET_VIEW / ASSET_EDIT,
and RLS on each table). Whether a service is due is worked out from the latest record of its
schedule and the highest meter values seen.
"""

import calendar
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app import authz
from app.db import asset_service as store
from app.db import assets as asset_store
from app.db import auth as audit
from app.db.database import Database
from app.services.auth import CurrentSession
from app.services.projects import ConflictError

ReadingRow = store.ReadingRow
ScheduleRow = store.ScheduleRow
RecordRow = store.RecordRow
UNITS = ("km", "mi")
SOON_DAYS = 30
SOON_SHARE = Decimal("0.1")  # within the last tenth of the distance or hours interval


class ServiceError(ValueError):
    """A request that can't be done as asked (shown to the person)."""


@dataclass(frozen=True, slots=True)
class Due:
    """When a scheduled service is next due. status: overdue | soon | ok | unknown."""

    status: str
    due_on: date | None
    due_distance: Decimal | None
    due_hours: Decimal | None


@dataclass(frozen=True, slots=True)
class ScheduleStatus:
    schedule: ScheduleRow
    last: RecordRow | None
    due: Due


@dataclass(frozen=True, slots=True)
class ServiceView:
    distance_unit: str
    distance: Decimal | None
    hours: Decimal | None
    readings: list[ReadingRow]
    schedules: list[ScheduleStatus]
    records: list[RecordRow]
    can_edit: bool


def add_months(day: date, months: int) -> date:
    """The same day `months` later (the month's last day when it's shorter)."""
    total = day.month - 1 + months
    year, month = day.year + total // 12, total % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def due(
    schedule: ScheduleRow,
    last: RecordRow | None,
    *,
    distance: Decimal | None,
    hours: Decimal | None,
    today: date,
) -> Due:
    """Next due date, distance and hours, whichever comes first. Without a record of the last
    service the status is unknown: the person adds when it was last done."""
    if last is None:
        return Due("unknown", None, None, None)
    due_on = add_months(last.done_on, schedule.every_months) if schedule.every_months else None
    due_distance = (
        last.distance + schedule.every_distance
        if schedule.every_distance is not None and last.distance is not None
        else None
    )
    due_hours = (
        last.hours + schedule.every_hours
        if schedule.every_hours is not None and last.hours is not None
        else None
    )
    overdue = (
        (due_on is not None and today >= due_on)
        or (due_distance is not None and distance is not None and distance >= due_distance)
        or (due_hours is not None and hours is not None and hours >= due_hours)
    )
    soon = (
        (due_on is not None and today >= due_on - timedelta(days=SOON_DAYS))
        or (
            due_distance is not None
            and distance is not None
            and schedule.every_distance is not None
            and distance >= due_distance - schedule.every_distance * SOON_SHARE
        )
        or (
            due_hours is not None
            and hours is not None
            and schedule.every_hours is not None
            and hours >= due_hours - schedule.every_hours * SOON_SHARE
        )
    )
    if due_on is None and due_distance is None and due_hours is None:
        status = "unknown"  # e.g. every 8,000 km, but the last record has no distance
    else:
        status = "overdue" if overdue else "soon" if soon else "ok"
    return Due(status, due_on, due_distance, due_hours)


async def _access(conn: Any, asset_id: uuid.UUID) -> authz.ProjectAccess:
    asset = await asset_store.get_asset(conn, asset_id)
    if asset is None:
        raise authz.NotFoundError("Not found.")
    return authz.ProjectAccess(asset.role)


def _can(session: CurrentSession, access: authz.ProjectAccess, write: bool) -> None:
    authz.require(session.principal, authz.Action.ASSET_VIEW, access)
    if write:
        authz.require(session.principal, authz.Action.ASSET_EDIT, access)


async def _audit(
    conn: Any, session: CurrentSession, action: str, kind: str, item: uuid.UUID, ip: str | None
) -> None:
    await audit.record_audit(
        conn,
        action=action,
        actor_user_id=session.user.id,
        ip=ip,
        resource_type=kind,
        resource_id=item,
    )


async def view(
    db: Database, session: CurrentSession, asset_id: uuid.UUID, *, today: date | None = None
) -> ServiceView:
    async with db.user_transaction(session.user.id) as conn:
        access = await _access(conn, asset_id)
        _can(session, access, write=False)
        unit = await store.distance_unit(conn, asset_id) or "km"
        distance, hours = await store.highest(conn, asset_id)
        lasts = await store.last_records(conn, asset_id)
        schedules = await store.schedules(conn, asset_id)
        day = today or datetime.now(UTC).date()
        return ServiceView(
            distance_unit=unit,
            distance=distance,
            hours=hours,
            readings=await store.readings(conn, asset_id, 20),
            schedules=[
                ScheduleStatus(
                    s,
                    lasts.get(s.id),
                    due(s, lasts.get(s.id), distance=distance, hours=hours, today=day),
                )
                for s in schedules
            ],
            records=await store.records(conn, asset_id, 200),
            can_edit=access.role in ("owner", "editor"),
        )


async def set_distance_unit(
    db: Database, session: CurrentSession, asset_id: uuid.UUID, unit: str
) -> None:
    if unit not in UNITS:
        raise ServiceError("Unknown unit.")
    async with db.user_transaction(session.user.id) as conn:
        _can(session, await _access(conn, asset_id), write=True)
        await store.set_distance_unit(conn, asset_id, unit)


async def add_reading(
    db: Database,
    session: CurrentSession,
    asset_id: uuid.UUID,
    *,
    read_on: date,
    distance: Decimal | None,
    hours: Decimal | None,
    ip: str | None,
) -> None:
    if distance is None and hours is None:
        raise ServiceError("Enter a distance or hours.")
    async with db.user_transaction(session.user.id) as conn:
        _can(session, await _access(conn, asset_id), write=True)
        reading_id = await store.add_reading(
            conn,
            asset_id=asset_id,
            user_id=session.user.id,
            read_on=read_on,
            distance=distance,
            hours=hours,
        )
        await _audit(conn, session, "asset_reading.created", "asset_reading", reading_id, ip)


async def delete_reading(
    db: Database, session: CurrentSession, reading_id: uuid.UUID, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        reading = await store.get_reading(conn, reading_id)
        if reading is None:
            raise authz.NotFoundError("Not found.")
        _can(session, await _access(conn, reading.asset_id), write=True)
        await store.delete_reading(conn, reading_id)
        await _audit(conn, session, "asset_reading.deleted", "asset_reading", reading_id, ip)


def _check_interval(
    every_distance: Decimal | None, every_hours: Decimal | None, every_months: int | None
) -> None:
    if every_distance is None and every_hours is None and every_months is None:
        raise ServiceError("Give at least one interval: distance, hours or months.")


async def create_schedule(
    db: Database,
    session: CurrentSession,
    asset_id: uuid.UUID,
    *,
    name: str,
    every_distance: Decimal | None,
    every_hours: Decimal | None,
    every_months: int | None,
    notes: str,
    ip: str | None,
) -> ScheduleRow:
    _check_interval(every_distance, every_hours, every_months)
    async with db.user_transaction(session.user.id) as conn:
        _can(session, await _access(conn, asset_id), write=True)
        schedule_id = await store.create_schedule(
            conn,
            asset_id=asset_id,
            user_id=session.user.id,
            name=name,
            every_distance=every_distance,
            every_hours=every_hours,
            every_months=every_months,
            notes=notes,
        )
        await _audit(conn, session, "service_schedule.created", "service_schedule", schedule_id, ip)
        row = await store.get_schedule(conn, schedule_id)
    if row is None:
        raise RuntimeError("created schedule not visible")
    return row


async def update_schedule(
    db: Database,
    session: CurrentSession,
    schedule_id: uuid.UUID,
    *,
    expected_version: int,
    name: str,
    every_distance: Decimal | None,
    every_hours: Decimal | None,
    every_months: int | None,
    notes: str,
    ip: str | None,
) -> ScheduleRow:
    _check_interval(every_distance, every_hours, every_months)
    async with db.user_transaction(session.user.id) as conn:
        before = await store.get_schedule(conn, schedule_id)
        if before is None:
            raise authz.NotFoundError("Not found.")
        _can(session, await _access(conn, before.asset_id), write=True)
        version = await store.update_schedule(
            conn,
            schedule_id,
            expected_version=expected_version,
            name=name,
            every_distance=every_distance,
            every_hours=every_hours,
            every_months=every_months,
            notes=notes,
        )
        if version is None:
            raise ConflictError("This schedule was changed elsewhere. Reload and try again.")
        await _audit(conn, session, "service_schedule.updated", "service_schedule", schedule_id, ip)
        row = await store.get_schedule(conn, schedule_id)
    if row is None:
        raise authz.NotFoundError("Not found.")
    return row


async def delete_schedule(
    db: Database, session: CurrentSession, schedule_id: uuid.UUID, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        before = await store.get_schedule(conn, schedule_id)
        if before is None:
            raise authz.NotFoundError("Not found.")
        _can(session, await _access(conn, before.asset_id), write=True)
        await store.delete_schedule(conn, schedule_id)
        await _audit(conn, session, "service_schedule.deleted", "service_schedule", schedule_id, ip)


async def add_record(
    db: Database,
    session: CurrentSession,
    asset_id: uuid.UUID,
    *,
    schedule_id: uuid.UUID | None,
    title: str | None,
    done_on: date,
    distance: Decimal | None,
    hours: Decimal | None,
    cost_cents: int | None,
    notes: str,
    ip: str | None,
) -> RecordRow:
    async with db.user_transaction(session.user.id) as conn:
        _can(session, await _access(conn, asset_id), write=True)
        if schedule_id is not None:
            schedule = await store.get_schedule(conn, schedule_id)
            if schedule is None or schedule.asset_id != asset_id:
                raise authz.NotFoundError("Not found.")
            title = title or schedule.name
        if not title:
            raise ServiceError("Say what was done.")
        record_id = await store.add_record(
            conn,
            asset_id=asset_id,
            user_id=session.user.id,
            schedule_id=schedule_id,
            title=title,
            done_on=done_on,
            distance=distance,
            hours=hours,
            cost_cents=cost_cents,
            notes=notes,
        )
        await _audit(conn, session, "service_record.created", "service_record", record_id, ip)
        row = await store.get_record(conn, record_id)
    if row is None:
        raise RuntimeError("created record not visible")
    return row


async def delete_record(
    db: Database, session: CurrentSession, record_id: uuid.UUID, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        before = await store.get_record(conn, record_id)
        if before is None:
            raise authz.NotFoundError("Not found.")
        _can(session, await _access(conn, before.asset_id), write=True)
        await store.delete_record(conn, record_id)
        await _audit(conn, session, "service_record.deleted", "service_record", record_id, ip)

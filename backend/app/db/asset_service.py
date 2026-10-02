"""Queries for asset readings, service schedules and service records (user transactions;
RLS: the asset's members read, its owners and editors write)."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class ReadingRow:
    id: uuid.UUID
    asset_id: uuid.UUID
    read_on: date
    distance: Decimal | None
    hours: Decimal | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    id: uuid.UUID
    asset_id: uuid.UUID
    name: str
    every_distance: Decimal | None
    every_hours: Decimal | None
    every_months: int | None
    notes: str
    version: int


@dataclass(frozen=True, slots=True)
class RecordRow:
    id: uuid.UUID
    asset_id: uuid.UUID
    schedule_id: uuid.UUID | None
    title: str
    done_on: date
    distance: Decimal | None
    hours: Decimal | None
    cost_cents: int | None
    notes: str
    created_at: datetime


async def distance_unit(conn: AsyncConnection, asset_id: uuid.UUID) -> str | None:
    value = await conn.scalar(
        text("SELECT distance_unit FROM assets WHERE id = :a AND deleted_at IS NULL"),
        {"a": asset_id},
    )
    return str(value) if value is not None else None


async def set_distance_unit(conn: AsyncConnection, asset_id: uuid.UUID, unit: str) -> None:
    await conn.execute(
        text("UPDATE assets SET distance_unit = :u WHERE id = :a AND deleted_at IS NULL"),
        {"a": asset_id, "u": unit},
    )


async def readings(conn: AsyncConnection, asset_id: uuid.UUID, limit: int) -> list[ReadingRow]:
    rows = await conn.execute(
        text("""
            SELECT id, asset_id, read_on, distance, hours, created_at FROM asset_readings
            WHERE asset_id = :a ORDER BY read_on DESC, created_at DESC LIMIT :n
        """),
        {"a": asset_id, "n": limit},
    )
    return [ReadingRow(**r._mapping) for r in rows]


async def highest(conn: AsyncConnection, asset_id: uuid.UUID) -> tuple[Decimal | None, ...]:
    """The highest distance and hours seen in readings and service records (meters only go
    up; a typo'd low reading doesn't make a service look due)."""
    row = (
        await conn.execute(
            text("""
                SELECT max(distance) AS distance, max(hours) AS hours FROM (
                    SELECT distance, hours FROM asset_readings WHERE asset_id = :a
                    UNION ALL
                    SELECT distance, hours FROM service_records
                    WHERE asset_id = :a AND deleted_at IS NULL
                ) seen
            """),
            {"a": asset_id},
        )
    ).one()
    return row.distance, row.hours


async def add_reading(
    conn: AsyncConnection,
    *,
    asset_id: uuid.UUID,
    user_id: uuid.UUID,
    read_on: date,
    distance: Decimal | None,
    hours: Decimal | None,
) -> uuid.UUID:
    reading_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO asset_readings (id, asset_id, read_on, distance, hours, created_by)
            VALUES (:id, :a, :d, :dist, :h, :u)
        """),
        {"id": reading_id, "a": asset_id, "d": read_on, "dist": distance, "h": hours, "u": user_id},
    )
    return reading_id


async def get_reading(conn: AsyncConnection, reading_id: uuid.UUID) -> ReadingRow | None:
    row = (
        await conn.execute(
            text(
                "SELECT id, asset_id, read_on, distance, hours, created_at FROM asset_readings "
                "WHERE id = :id"
            ),
            {"id": reading_id},
        )
    ).first()
    return ReadingRow(**row._mapping) if row else None


async def delete_reading(conn: AsyncConnection, reading_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM asset_readings WHERE id = :id"), {"id": reading_id})


async def schedules(conn: AsyncConnection, asset_id: uuid.UUID) -> list[ScheduleRow]:
    rows = await conn.execute(
        text("""
            SELECT id, asset_id, name, every_distance, every_hours, every_months, notes, version
            FROM service_schedules WHERE asset_id = :a AND deleted_at IS NULL
            ORDER BY created_at LIMIT 200
        """),
        {"a": asset_id},
    )
    return [ScheduleRow(**r._mapping) for r in rows]


async def get_schedule(conn: AsyncConnection, schedule_id: uuid.UUID) -> ScheduleRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, asset_id, name, every_distance, every_hours, every_months, notes,
                       version
                FROM service_schedules WHERE id = :id AND deleted_at IS NULL
            """),
            {"id": schedule_id},
        )
    ).first()
    return ScheduleRow(**row._mapping) if row else None


async def create_schedule(
    conn: AsyncConnection,
    *,
    asset_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    every_distance: Decimal | None,
    every_hours: Decimal | None,
    every_months: int | None,
    notes: str,
) -> uuid.UUID:
    schedule_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO service_schedules (id, asset_id, name, every_distance, every_hours,
                                           every_months, notes, created_by)
            VALUES (:id, :a, :n, :d, :h, :m, :notes, :u)
        """),
        {
            "id": schedule_id,
            "a": asset_id,
            "n": name,
            "d": every_distance,
            "h": every_hours,
            "m": every_months,
            "notes": notes,
            "u": user_id,
        },
    )
    return schedule_id


async def update_schedule(
    conn: AsyncConnection,
    schedule_id: uuid.UUID,
    *,
    expected_version: int,
    name: str,
    every_distance: Decimal | None,
    every_hours: Decimal | None,
    every_months: int | None,
    notes: str,
) -> int | None:
    v = await conn.scalar(
        text("""
            UPDATE service_schedules SET name = :n, every_distance = :d, every_hours = :h,
                   every_months = :m, notes = :notes, updated_at = now(), version = version + 1
            WHERE id = :id AND version = :v AND deleted_at IS NULL RETURNING version
        """),
        {
            "id": schedule_id,
            "v": expected_version,
            "n": name,
            "d": every_distance,
            "h": every_hours,
            "m": every_months,
            "notes": notes,
        },
    )
    return int(v) if v is not None else None


async def delete_schedule(conn: AsyncConnection, schedule_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE service_schedules SET deleted_at = now(), updated_at = now(), "
            "version = version + 1 WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": schedule_id},
    )


async def records(conn: AsyncConnection, asset_id: uuid.UUID, limit: int) -> list[RecordRow]:
    rows = await conn.execute(
        text("""
            SELECT id, asset_id, schedule_id, title, done_on, distance, hours, cost_cents, notes,
                   created_at
            FROM service_records WHERE asset_id = :a AND deleted_at IS NULL
            ORDER BY done_on DESC, created_at DESC LIMIT :n
        """),
        {"a": asset_id, "n": limit},
    )
    return [RecordRow(**r._mapping) for r in rows]


async def last_records(conn: AsyncConnection, asset_id: uuid.UUID) -> dict[uuid.UUID, RecordRow]:
    """The latest record of each schedule of the asset."""
    rows = await conn.execute(
        text("""
            SELECT DISTINCT ON (schedule_id) id, asset_id, schedule_id, title, done_on, distance,
                   hours, cost_cents, notes, created_at
            FROM service_records
            WHERE asset_id = :a AND schedule_id IS NOT NULL AND deleted_at IS NULL
            ORDER BY schedule_id, done_on DESC, created_at DESC
        """),
        {"a": asset_id},
    )
    found = [RecordRow(**r._mapping) for r in rows]
    return {r.schedule_id: r for r in found if r.schedule_id is not None}


async def get_record(conn: AsyncConnection, record_id: uuid.UUID) -> RecordRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, asset_id, schedule_id, title, done_on, distance, hours, cost_cents,
                       notes, created_at
                FROM service_records WHERE id = :id AND deleted_at IS NULL
            """),
            {"id": record_id},
        )
    ).first()
    return RecordRow(**row._mapping) if row else None


async def add_record(
    conn: AsyncConnection,
    *,
    asset_id: uuid.UUID,
    user_id: uuid.UUID,
    schedule_id: uuid.UUID | None,
    title: str,
    done_on: date,
    distance: Decimal | None,
    hours: Decimal | None,
    cost_cents: int | None,
    notes: str,
) -> uuid.UUID:
    record_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO service_records (id, asset_id, schedule_id, title, done_on, distance,
                                         hours, cost_cents, notes, created_by)
            VALUES (:id, :a, :s, :t, :d, :dist, :h, :c, :notes, :u)
        """),
        {
            "id": record_id,
            "a": asset_id,
            "s": schedule_id,
            "t": title,
            "d": done_on,
            "dist": distance,
            "h": hours,
            "c": cost_cents,
            "notes": notes,
            "u": user_id,
        },
    )
    return record_id


async def delete_record(conn: AsyncConnection, record_id: uuid.UUID) -> None:
    await conn.execute(
        text("UPDATE service_records SET deleted_at = now() WHERE id = :id AND deleted_at IS NULL"),
        {"id": record_id},
    )

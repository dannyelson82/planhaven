"""Queries for assets, their members and the projects linked to them."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class AssetRow:
    id: uuid.UUID
    name: str
    kind: str
    details: list[dict[str, str]]
    notes: str
    role: str | None
    updated_at: datetime
    version: int
    projects: int
    photo_sha256: str | None = None
    photo_thumb_sha256: str | None = None
    photo_type: str | None = None


@dataclass(frozen=True, slots=True)
class LinkedProject:
    id: uuid.UUID
    title: str
    stage: str
    updated_at: datetime


def _row(r: Any) -> AssetRow:
    values = dict(r._mapping)
    if isinstance(values["details"], str):
        values["details"] = json.loads(values["details"])
    return AssetRow(**values)


async def role(conn: AsyncConnection, asset_id: uuid.UUID) -> str | None:
    value = await conn.scalar(text("SELECT app.asset_role(:a)"), {"a": asset_id})
    return str(value) if value is not None else None


async def list_assets(conn: AsyncConnection) -> list[AssetRow]:
    rows = await conn.execute(
        text("""
            SELECT a.id, a.name, a.kind, a.details, a.notes, app.asset_role(a.id) AS role,
                   a.updated_at, a.version,
                   (SELECT count(*) FROM projects p WHERE p.asset_id = a.id
                      AND p.deleted_at IS NULL) AS projects,
                   a.photo_sha256, a.photo_thumb_sha256, a.photo_type
            FROM assets a WHERE a.deleted_at IS NULL
            ORDER BY a.name LIMIT 500
        """)
    )
    return [_row(r) for r in rows]


async def get_asset(conn: AsyncConnection, asset_id: uuid.UUID) -> AssetRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT a.id, a.name, a.kind, a.details, a.notes, app.asset_role(a.id) AS role,
                       a.updated_at, a.version,
                       (SELECT count(*) FROM projects p WHERE p.asset_id = a.id
                          AND p.deleted_at IS NULL) AS projects,
                       a.photo_sha256, a.photo_thumb_sha256, a.photo_type
                FROM assets a WHERE a.id = :id AND a.deleted_at IS NULL
            """),
            {"id": asset_id},
        )
    ).first()
    return _row(row) if row else None


async def create_asset(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    name: str,
    kind: str,
    details: list[dict[str, str]],
    notes: str,
) -> uuid.UUID:
    asset_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO assets (id, name, kind, details, notes, created_by)
            VALUES (:id, :n, :k, CAST(:d AS jsonb), :notes, :u)
        """),
        {
            "id": asset_id,
            "n": name,
            "k": kind,
            "d": json.dumps(details),
            "notes": notes,
            "u": user_id,
        },
    )
    await conn.execute(
        text("INSERT INTO asset_members (asset_id, user_id, role) VALUES (:a, :u, 'owner')"),
        {"a": asset_id, "u": user_id},
    )
    return asset_id


async def update_asset(
    conn: AsyncConnection,
    asset_id: uuid.UUID,
    expected_version: int,
    *,
    name: str,
    kind: str,
    details: list[dict[str, str]],
    notes: str,
) -> int | None:
    v = await conn.scalar(
        text("""
            UPDATE assets SET name = :n, kind = :k, details = CAST(:d AS jsonb), notes = :notes,
                              updated_at = now(), version = version + 1
            WHERE id = :id AND version = :v AND deleted_at IS NULL RETURNING version
        """),
        {
            "id": asset_id,
            "v": expected_version,
            "n": name,
            "k": kind,
            "d": json.dumps(details),
            "notes": notes,
        },
    )
    return int(v) if v is not None else None


async def delete_asset(conn: AsyncConnection, asset_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE assets SET deleted_at = now(), updated_at = now(), version = version + 1 "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": asset_id},
    )


async def linked_projects(conn: AsyncConnection, asset_id: uuid.UUID) -> list[LinkedProject]:
    """The asset's service history: linked projects this user can see (RLS)."""
    rows = await conn.execute(
        text("""
            SELECT id, title, stage, updated_at FROM projects
            WHERE asset_id = :a AND deleted_at IS NULL
            ORDER BY updated_at DESC LIMIT 500
        """),
        {"a": asset_id},
    )
    return [LinkedProject(**r._mapping) for r in rows]


async def set_project_asset(
    conn: AsyncConnection, project_id: uuid.UUID, asset_id: uuid.UUID | None
) -> bool:
    result = await conn.execute(
        text("""
            UPDATE projects SET asset_id = :a, updated_at = now(), version = version + 1
            WHERE id = :p AND deleted_at IS NULL
        """),
        {"p": project_id, "a": asset_id},
    )
    return result.rowcount == 1


async def set_photo(
    conn: AsyncConnection,
    asset_id: uuid.UUID,
    photo: str | None,
    thumb: str | None,
    content_type: str | None,
) -> bool:
    result = await conn.execute(
        text("""
            UPDATE assets SET photo_sha256 = :p, photo_thumb_sha256 = :t, photo_type = :ct,
                              updated_at = now(), version = version + 1
            WHERE id = :id AND deleted_at IS NULL
        """),
        {"id": asset_id, "p": photo, "t": thumb, "ct": content_type},
    )
    return result.rowcount == 1

"""Queries for project page layouts (user transactions; RLS applies)."""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


def _tiles(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, str):
        value = json.loads(value)
    return [t for t in value if isinstance(t, dict)] if isinstance(value, list) else None


async def own(conn: AsyncConnection, project_id: uuid.UUID) -> list[dict[str, Any]] | None:
    value = await conn.scalar(
        text(
            "SELECT tiles FROM project_layouts "
            "WHERE project_id = :p AND user_id = app.current_user_id()"
        ),
        {"p": project_id},
    )
    return _tiles(value)


async def owners(conn: AsyncConnection, project_id: uuid.UUID) -> list[dict[str, Any]] | None:
    """The layout of the project's owner (who shared it), if they arranged it."""
    value = await conn.scalar(
        text("""
            SELECT l.tiles FROM project_layouts l
            JOIN project_members m ON m.project_id = l.project_id AND m.user_id = l.user_id
            WHERE l.project_id = :p AND m.role = 'owner'
            LIMIT 1
        """),
        {"p": project_id},
    )
    return _tiles(value)


async def save(conn: AsyncConnection, project_id: uuid.UUID, tiles: list[dict[str, Any]]) -> None:
    await conn.execute(
        text("""
            INSERT INTO project_layouts (project_id, user_id, tiles)
            VALUES (:p, app.current_user_id(), CAST(:t AS jsonb))
            ON CONFLICT (project_id, user_id)
            DO UPDATE SET tiles = EXCLUDED.tiles, updated_at = now()
        """),
        {"p": project_id, "t": json.dumps(tiles)},
    )


async def reset(conn: AsyncConnection, project_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "DELETE FROM project_layouts WHERE project_id = :p AND user_id = app.current_user_id()"
        ),
        {"p": project_id},
    )

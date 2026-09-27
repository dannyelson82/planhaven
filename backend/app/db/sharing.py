"""Queries for project membership and the household directory."""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class MemberRow:
    user_id: uuid.UUID
    display_name: str
    email: str
    role: str


@dataclass(frozen=True, slots=True)
class DirectoryRow:
    id: uuid.UUID
    display_name: str
    email: str


async def members(conn: AsyncConnection, project_id: uuid.UUID) -> list[MemberRow]:
    """System context: names of members of a project the caller was authorized to view."""
    rows = await conn.execute(
        text("""
            SELECT m.user_id, u.display_name, u.email, m.role
            FROM project_members m JOIN users u ON u.id = m.user_id
            WHERE m.project_id = :p
            ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,
                     u.display_name
        """),
        {"p": project_id},
    )
    return [MemberRow(**r._mapping) for r in rows]


async def directory(conn: AsyncConnection, exclude: uuid.UUID) -> list[DirectoryRow]:
    """System context: active household members (names and emails only)."""
    rows = await conn.execute(
        text("""
            SELECT id, display_name, email FROM users
            WHERE disabled_at IS NULL AND id <> :me ORDER BY display_name LIMIT 500
        """),
        {"me": exclude},
    )
    return [DirectoryRow(**r._mapping) for r in rows]


async def active_user_exists(conn: AsyncConnection, user_id: uuid.UUID) -> bool:
    return bool(
        await conn.scalar(
            text("SELECT EXISTS (SELECT 1 FROM users WHERE id = :u AND disabled_at IS NULL)"),
            {"u": user_id},
        )
    )


async def add_member(
    conn: AsyncConnection, project_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> bool:
    result = await conn.execute(
        text(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (:p, :u, :r) "
            "ON CONFLICT (project_id, user_id) DO NOTHING"
        ),
        {"p": project_id, "u": user_id, "r": role},
    )
    return result.rowcount == 1


async def set_role(
    conn: AsyncConnection, project_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> bool:
    result = await conn.execute(
        text("UPDATE project_members SET role = :r WHERE project_id = :p AND user_id = :u"),
        {"p": project_id, "u": user_id, "r": role},
    )
    return result.rowcount == 1


async def remove(conn: AsyncConnection, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    result = await conn.execute(
        text("DELETE FROM project_members WHERE project_id = :p AND user_id = :u"),
        {"p": project_id, "u": user_id},
    )
    return result.rowcount == 1

"""Queries for membership of projects, assets, contacts and templates, and the household
directory."""

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


# Full query text per kind of shared thing (never assembled from pieces).
_QUERIES: dict[str, dict[str, str]] = {
    "project": {
        "members": """
            SELECT m.user_id, u.display_name, u.email, m.role
            FROM project_members m JOIN users u ON u.id = m.user_id
            WHERE m.project_id = :r
            ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,
                     u.display_name
        """,
        "add": "INSERT INTO project_members (project_id, user_id, role) VALUES (:r, :u, :role) "
        "ON CONFLICT (project_id, user_id) DO NOTHING",
        "set_role": "UPDATE project_members SET role = :role "
        "WHERE project_id = :r AND user_id = :u",
        "remove": "DELETE FROM project_members WHERE project_id = :r AND user_id = :u",
    },
    "asset": {
        "members": """
            SELECT m.user_id, u.display_name, u.email, m.role
            FROM asset_members m JOIN users u ON u.id = m.user_id
            WHERE m.asset_id = :r
            ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,
                     u.display_name
        """,
        "add": "INSERT INTO asset_members (asset_id, user_id, role) VALUES (:r, :u, :role) "
        "ON CONFLICT (asset_id, user_id) DO NOTHING",
        "set_role": "UPDATE asset_members SET role = :role WHERE asset_id = :r AND user_id = :u",
        "remove": "DELETE FROM asset_members WHERE asset_id = :r AND user_id = :u",
    },
    "contact": {
        "members": """
            SELECT m.user_id, u.display_name, u.email, m.role
            FROM contact_members m JOIN users u ON u.id = m.user_id
            WHERE m.contact_id = :r
            ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,
                     u.display_name
        """,
        "add": "INSERT INTO contact_members (contact_id, user_id, role) VALUES (:r, :u, :role) "
        "ON CONFLICT (contact_id, user_id) DO NOTHING",
        "set_role": "UPDATE contact_members SET role = :role "
        "WHERE contact_id = :r AND user_id = :u",
        "remove": "DELETE FROM contact_members WHERE contact_id = :r AND user_id = :u",
    },
    "template": {
        "members": """
            SELECT m.user_id, u.display_name, u.email, m.role
            FROM template_members m JOIN users u ON u.id = m.user_id
            WHERE m.template_id = :r
            ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,
                     u.display_name
        """,
        "add": "INSERT INTO template_members (template_id, user_id, role) "
        "VALUES (:r, :u, :role) ON CONFLICT (template_id, user_id) DO NOTHING",
        "set_role": "UPDATE template_members SET role = :role "
        "WHERE template_id = :r AND user_id = :u",
        "remove": "DELETE FROM template_members WHERE template_id = :r AND user_id = :u",
    },
}


async def members(
    conn: AsyncConnection, resource_id: uuid.UUID, kind: str = "project"
) -> list[MemberRow]:
    """System context: members of a project or asset the caller was authorized to view."""
    rows = await conn.execute(text(_QUERIES[kind]["members"]), {"r": resource_id})
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
    conn: AsyncConnection,
    resource_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    kind: str = "project",
) -> bool:
    result = await conn.execute(
        text(_QUERIES[kind]["add"]), {"r": resource_id, "u": user_id, "role": role}
    )
    return result.rowcount == 1


async def set_role(
    conn: AsyncConnection,
    resource_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    kind: str = "project",
) -> bool:
    result = await conn.execute(
        text(_QUERIES[kind]["set_role"]), {"r": resource_id, "u": user_id, "role": role}
    )
    return result.rowcount == 1


async def remove(
    conn: AsyncConnection, resource_id: uuid.UUID, user_id: uuid.UUID, kind: str = "project"
) -> bool:
    result = await conn.execute(text(_QUERIES[kind]["remove"]), {"r": resource_id, "u": user_id})
    return result.rowcount == 1

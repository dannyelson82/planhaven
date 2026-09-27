"""Queries for the trash: deleted things that can still be restored, and the final purge."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class TrashRow:
    kind: str
    id: uuid.UUID
    title: str
    project_id: uuid.UUID | None
    project_title: str | None
    deleted_at: datetime


async def trash(conn: AsyncConnection) -> list[TrashRow]:
    """What this user may restore (RLS, plus the same role rules the service enforces)."""
    rows = await conn.execute(
        text("""
            SELECT 'project' AS kind, p.id, p.title, NULL::uuid AS project_id,
                   NULL::text AS project_title, p.deleted_at
            FROM projects p
            WHERE p.deleted_at > now() - interval '30 days' AND app.project_role(p.id) = 'owner'
            UNION ALL
            SELECT 'task', t.id, t.title, t.project_id, p.title, t.deleted_at
            FROM tasks t JOIN projects p ON p.id = t.project_id AND p.deleted_at IS NULL
            WHERE t.deleted_at > now() - interval '30 days' AND app.can_write(t.project_id)
            UNION ALL
            SELECT 'list', l.id, l.title, l.project_id, p.title, l.deleted_at
            FROM lists l JOIN projects p ON p.id = l.project_id AND p.deleted_at IS NULL
            WHERE l.deleted_at > now() - interval '30 days' AND app.can_write(l.project_id)
            UNION ALL
            SELECT 'note', n.id, n.title, n.project_id, p.title, n.deleted_at
            FROM notes n JOIN projects p ON p.id = n.project_id AND p.deleted_at IS NULL
            WHERE n.deleted_at > now() - interval '30 days' AND app.can_write(n.project_id)
            UNION ALL
            SELECT 'attachment', a.id, a.filename, a.project_id, p.title, a.deleted_at
            FROM attachments a JOIN projects p ON p.id = a.project_id AND p.deleted_at IS NULL
            WHERE a.deleted_at > now() - interval '30 days' AND app.can_write(a.project_id)
            UNION ALL
            SELECT 'asset', s.id, s.name, NULL::uuid, NULL::text, s.deleted_at
            FROM assets s
            WHERE s.deleted_at > now() - interval '30 days' AND app.asset_role(s.id) = 'owner'
            ORDER BY deleted_at DESC LIMIT 200
        """)
    )
    return [TrashRow(**r._mapping) for r in rows]


# The parent project of a deleted child (None when the item or its project is gone).
_PARENT = {
    "task": "SELECT project_id FROM tasks WHERE id = :id AND deleted_at IS NOT NULL",
    "list": "SELECT project_id FROM lists WHERE id = :id AND deleted_at IS NOT NULL",
    "note": "SELECT project_id FROM notes WHERE id = :id AND deleted_at IS NOT NULL",
    "attachment": "SELECT project_id FROM attachments WHERE id = :id AND deleted_at IS NOT NULL",
}

_RESTORE = {
    "project": "UPDATE projects SET deleted_at = NULL, updated_at = now(), version = version + 1 "
    "WHERE id = :id AND deleted_at > now() - interval '30 days'",
    "task": "UPDATE tasks SET deleted_at = NULL, updated_at = now(), version = version + 1 "
    "WHERE id = :id AND deleted_at > now() - interval '30 days'",
    "list": "UPDATE lists SET deleted_at = NULL, updated_at = now(), version = version + 1 "
    "WHERE id = :id AND deleted_at > now() - interval '30 days'",
    "note": "UPDATE notes SET deleted_at = NULL, updated_at = now(), version = version + 1 "
    "WHERE id = :id AND deleted_at > now() - interval '30 days'",
    "attachment": "UPDATE attachments SET deleted_at = NULL "
    "WHERE id = :id AND deleted_at > now() - interval '30 days'",
    "asset": "UPDATE assets SET deleted_at = NULL, updated_at = now(), version = version + 1 "
    "WHERE id = :id AND deleted_at > now() - interval '30 days'",
}


async def parent_project(conn: AsyncConnection, kind: str, item_id: uuid.UUID) -> uuid.UUID | None:
    value = await conn.scalar(text(_PARENT[kind]), {"id": item_id})
    return value if isinstance(value, uuid.UUID) else None


async def project_deleted(conn: AsyncConnection, project_id: uuid.UUID) -> bool:
    return bool(
        await conn.scalar(
            text("SELECT deleted_at IS NOT NULL FROM projects WHERE id = :id"), {"id": project_id}
        )
    )


async def restore(conn: AsyncConnection, kind: str, item_id: uuid.UUID) -> bool:
    result = await conn.execute(text(_RESTORE[kind]), {"id": item_id})
    return result.rowcount == 1


async def purge(conn: AsyncConnection) -> int:
    """System context: remove everything deleted more than 30 days ago (migration 0015)."""
    return int(await conn.scalar(text("SELECT app.purge_trash()")) or 0)

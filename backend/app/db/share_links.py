"""Queries for share links (ADR 0015, migration 0026).

Management runs in user transactions (project editors); opening a link and loading a guest's
session run in the system context; everything a guest reads or changes runs in a link
transaction, where RLS allows only what the link was given.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class LinkRow:
    id: uuid.UUID
    project_id: uuid.UUID
    created_by: uuid.UUID
    name: str
    pin_hash: str | None
    tasks_view: str
    tasks_tick: bool
    files_view: bool
    files_add: bool
    lists_tick: bool
    append_note_id: uuid.UUID | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


# ---------------------------------------------------------------- management (editors)


async def create_link(conn: AsyncConnection, values: dict[str, Any]) -> uuid.UUID:
    link_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO share_links (id, project_id, created_by, name, token_hash, pin_hash,
                                     tasks_view, tasks_tick, files_view, files_add, lists_tick,
                                     append_note_id, expires_at)
            VALUES (:id, :project_id, :created_by, :name, :token_hash, :pin_hash, :tasks_view,
                    :tasks_tick, :files_view, :files_add, :lists_tick, :append_note_id,
                    now() + make_interval(days => :days))
        """),
        {"id": link_id, **values},
    )
    return link_id


async def add_items(
    conn: AsyncConnection, link_id: uuid.UUID, kind: str, item_ids: list[uuid.UUID]
) -> None:
    for item_id in item_ids:
        await conn.execute(
            text(
                "INSERT INTO share_link_items (link_id, kind, item_id) VALUES (:l, :k, :i) "
                "ON CONFLICT DO NOTHING"
            ),
            {"l": link_id, "k": kind, "i": item_id},
        )


async def items(conn: AsyncConnection, link_id: uuid.UUID) -> dict[str, list[uuid.UUID]]:
    rows = await conn.execute(
        text("SELECT kind, item_id FROM share_link_items WHERE link_id = :l"), {"l": link_id}
    )
    found: dict[str, list[uuid.UUID]] = {"task": [], "note": [], "list": []}
    for r in rows:
        found[r.kind].append(r.item_id)
    return found


async def links_for_project(conn: AsyncConnection, project_id: uuid.UUID) -> list[LinkRow]:
    rows = await conn.execute(
        text("""
            SELECT id, project_id, created_by, name, pin_hash, tasks_view, tasks_tick,
                   files_view, files_add, lists_tick, append_note_id, created_at, expires_at,
                   revoked_at, last_used_at
            FROM share_links WHERE project_id = :p ORDER BY created_at DESC LIMIT 200
        """),
        {"p": project_id},
    )
    return [LinkRow(**r._mapping) for r in rows]


async def get_link(conn: AsyncConnection, link_id: uuid.UUID) -> LinkRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, project_id, created_by, name, pin_hash, tasks_view, tasks_tick,
                       files_view, files_add, lists_tick, append_note_id, created_at,
                       expires_at, revoked_at, last_used_at
                FROM share_links WHERE id = :l
            """),
            {"l": link_id},
        )
    ).first()
    return LinkRow(**row._mapping) if row else None


async def revoke(conn: AsyncConnection, link_id: uuid.UUID) -> None:
    await conn.execute(
        text("UPDATE share_links SET revoked_at = now() WHERE id = :l AND revoked_at IS NULL"),
        {"l": link_id},
    )


@dataclass(frozen=True, slots=True)
class EventRow:
    at: datetime
    guest_name: str
    action: str
    detail: str


async def events(conn: AsyncConnection, link_id: uuid.UUID, limit: int = 200) -> list[EventRow]:
    rows = await conn.execute(
        text("""
            SELECT at, guest_name, action, detail FROM share_link_events
            WHERE link_id = :l ORDER BY at DESC LIMIT :n
        """),
        {"l": link_id, "n": limit},
    )
    return [EventRow(**r._mapping) for r in rows]


# ---------------------------------------------------------------- opening a link (system)


async def live_link_by_token(conn: AsyncConnection, token_hash: str) -> LinkRow | None:
    """System context: the link with this token, if it still works (not revoked or expired;
    its creator's account active and still able to edit the project; project not deleted)."""
    row = (
        await conn.execute(
            text("""
                SELECT l.id, l.project_id, l.created_by, l.name, l.pin_hash, l.tasks_view,
                       l.tasks_tick, l.files_view, l.files_add, l.lists_tick, l.append_note_id,
                       l.created_at, l.expires_at, l.revoked_at, l.last_used_at
                FROM share_links l
                JOIN users u ON u.id = l.created_by AND u.disabled_at IS NULL
                JOIN projects p ON p.id = l.project_id AND p.deleted_at IS NULL
                JOIN project_members m ON m.project_id = l.project_id
                                      AND m.user_id = l.created_by
                                      AND m.role IN ('owner', 'editor')
                WHERE l.token_hash = :h AND l.revoked_at IS NULL AND l.expires_at > now()
            """),
            {"h": token_hash},
        )
    ).first()
    return LinkRow(**row._mapping) if row else None


async def create_session(
    conn: AsyncConnection, token_hash: str, link: LinkRow, guest_name: str, hours: int
) -> datetime:
    expires = await conn.scalar(
        text("""
            INSERT INTO share_sessions (token_hash, link_id, guest_name, expires_at)
            VALUES (:h, :l, :n, least(now() + make_interval(hours => :hours), :link_expires))
            RETURNING expires_at
        """),
        {
            "h": token_hash,
            "l": link.id,
            "n": guest_name,
            "hours": hours,
            "link_expires": link.expires_at,
        },
    )
    await conn.execute(
        text("UPDATE share_links SET last_used_at = now() WHERE id = :l"), {"l": link.id}
    )
    return expires  # type: ignore[no-any-return]


async def live_session(conn: AsyncConnection, token_hash: str) -> tuple[LinkRow, str] | None:
    """System context: the guest's link and name, if both still work (as live_link_by_token)."""
    row = (
        await conn.execute(
            text("""
                SELECT l.id, l.project_id, l.created_by, l.name, l.pin_hash, l.tasks_view,
                       l.tasks_tick, l.files_view, l.files_add, l.lists_tick, l.append_note_id,
                       l.created_at, l.expires_at, l.revoked_at, l.last_used_at,
                       s.guest_name
                FROM share_sessions s
                JOIN share_links l ON l.id = s.link_id
                JOIN users u ON u.id = l.created_by AND u.disabled_at IS NULL
                JOIN projects p ON p.id = l.project_id AND p.deleted_at IS NULL
                JOIN project_members m ON m.project_id = l.project_id
                                      AND m.user_id = l.created_by
                                      AND m.role IN ('owner', 'editor')
                WHERE s.token_hash = :h AND s.expires_at > now()
                  AND l.revoked_at IS NULL AND l.expires_at > now()
            """),
            {"h": token_hash},
        )
    ).first()
    if row is None:
        return None
    values = dict(row._mapping)
    guest = values.pop("guest_name")
    return LinkRow(**values), guest


async def touch(conn: AsyncConnection, link_id: uuid.UUID) -> None:
    await conn.execute(
        text("""
            UPDATE share_links SET last_used_at = now()
            WHERE id = :l AND (last_used_at IS NULL OR last_used_at < now() - interval '5 minutes')
        """),
        {"l": link_id},
    )


async def end_session(conn: AsyncConnection, token_hash: str) -> None:
    await conn.execute(text("DELETE FROM share_sessions WHERE token_hash = :h"), {"h": token_hash})


async def record(
    conn: AsyncConnection, link_id: uuid.UUID, guest_name: str, action: str, detail: str = ""
) -> None:
    await conn.execute(
        text("""
            INSERT INTO share_link_events (link_id, guest_name, action, detail)
            VALUES (:l, :n, :a, :d)
        """),
        {"l": link_id, "n": guest_name, "a": action, "d": detail[:300]},
    )


# ---------------------------------------------------------------- what a guest sees (link tx)


async def guest_project_title(conn: AsyncConnection, project_id: uuid.UUID) -> str | None:
    value = await conn.scalar(
        text("SELECT title FROM projects WHERE id = :p AND deleted_at IS NULL"), {"p": project_id}
    )
    return str(value) if value is not None else None


async def guest_tasks(conn: AsyncConnection, project_id: uuid.UUID) -> list[Any]:
    rows = await conn.execute(
        text("""
            SELECT id, title, notes, done_at FROM tasks
            WHERE project_id = :p AND deleted_at IS NULL ORDER BY position, created_at
            LIMIT 500
        """),
        {"p": project_id},
    )
    return list(rows)


async def guest_notes(conn: AsyncConnection, project_id: uuid.UUID) -> list[Any]:
    rows = await conn.execute(
        text("""
            SELECT id, title, content, version FROM notes
            WHERE project_id = :p AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 100
        """),
        {"p": project_id},
    )
    return list(rows)


async def guest_lists(conn: AsyncConnection, project_id: uuid.UUID) -> list[Any]:
    rows = await conn.execute(
        text("""
            SELECT id, title, kind FROM lists
            WHERE project_id = :p AND deleted_at IS NULL ORDER BY position, created_at
            LIMIT 100
        """),
        {"p": project_id},
    )
    return list(rows)


async def guest_list_items(conn: AsyncConnection, project_id: uuid.UUID) -> list[Any]:
    rows = await conn.execute(
        text("""
            SELECT id, list_id, text, quantity, unit, checked_at FROM list_items
            WHERE project_id = :p AND deleted_at IS NULL ORDER BY position, created_at
            LIMIT 2000
        """),
        {"p": project_id},
    )
    return list(rows)


async def guest_files(conn: AsyncConnection, project_id: uuid.UUID) -> list[Any]:
    rows = await conn.execute(
        text("""
            SELECT id, filename, kind, size, content_type, blob_sha256, thumb_sha256,
                   metadata_kept
            FROM attachments WHERE project_id = :p AND deleted_at IS NULL
            ORDER BY created_at DESC LIMIT 500
        """),
        {"p": project_id},
    )
    return list(rows)


async def guest_tick_task(
    conn: AsyncConnection, project_id: uuid.UUID, task_id: uuid.UUID, done: bool
) -> str | None:
    """Tick (or untick) a task; its title, or None if the link can't."""
    value = await conn.scalar(
        text("""
            UPDATE tasks SET done_at = CASE WHEN :done THEN coalesce(done_at, now()) END,
                             done_by = NULL, updated_at = now(), version = version + 1
            WHERE id = :t AND project_id = :p AND deleted_at IS NULL
            RETURNING title
        """),
        {"t": task_id, "p": project_id, "done": done},
    )
    return str(value) if value is not None else None


async def guest_tick_item(
    conn: AsyncConnection, project_id: uuid.UUID, item_id: uuid.UUID, checked: bool
) -> str | None:
    value = await conn.scalar(
        text("""
            UPDATE list_items SET checked_at = CASE WHEN :c THEN coalesce(checked_at, now()) END,
                                  checked_by = NULL, updated_at = now(),
                                  version = version + 1
            WHERE id = :i AND project_id = :p AND deleted_at IS NULL
            RETURNING text
        """),
        {"i": item_id, "p": project_id, "c": checked},
    )
    return str(value) if value is not None else None


_OWNED = {
    "tasks": "SELECT count(*) FROM tasks WHERE id = ANY(:ids) AND project_id = :p "
    "AND deleted_at IS NULL",
    "notes": "SELECT count(*) FROM notes WHERE id = ANY(:ids) AND project_id = :p "
    "AND deleted_at IS NULL",
    "lists": "SELECT count(*) FROM lists WHERE id = ANY(:ids) AND project_id = :p "
    "AND deleted_at IS NULL",
}


async def all_in_project(
    conn: AsyncConnection, table: str, project_id: uuid.UUID, ids: list[uuid.UUID]
) -> bool:
    """Every id is a (not deleted) task, note or list of this project."""
    if not ids:
        return True
    count = await conn.scalar(text(_OWNED[table]), {"ids": ids, "p": project_id})
    return bool(count == len(set(ids)))


async def end_sessions(conn: AsyncConnection, link_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM share_sessions WHERE link_id = :l"), {"l": link_id})


async def list_of_item(conn: AsyncConnection, item_id: uuid.UUID) -> uuid.UUID | None:
    value = await conn.scalar(
        text("SELECT list_id FROM list_items WHERE id = :i AND deleted_at IS NULL"), {"i": item_id}
    )
    return value if isinstance(value, uuid.UUID) else None


async def link_creator(conn: AsyncConnection) -> uuid.UUID:
    value = await conn.scalar(text("SELECT app.link_creator()"))
    if not isinstance(value, uuid.UUID):
        raise RuntimeError("no share link in this transaction")
    return value

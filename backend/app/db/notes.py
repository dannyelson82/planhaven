"""Queries for notes. (The CRDT update tables are only read, to convert notes saved by the
earlier live editor.)"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class NoteRow:
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    text_content: str
    source: str
    updated_at: datetime
    version: int
    archived_at: datetime | None


async def notes_for_project(
    conn: AsyncConnection, project_id: uuid.UUID, *, archived: bool = False
) -> list[NoteRow]:
    """The project's notes on its page, or (archived=True) the archived ones."""
    rows = await conn.execute(
        text("""
            SELECT id, project_id, title, left(text_content, 300) AS text_content, source,
                   updated_at, version, archived_at
            FROM notes WHERE project_id = :p AND deleted_at IS NULL
              AND (archived_at IS NOT NULL) = :a
            ORDER BY coalesce(archived_at, created_at) DESC LIMIT 500
        """),
        {"p": project_id, "a": archived},
    )
    return [NoteRow(**r._mapping) for r in rows]


async def unconverted(conn: AsyncConnection, project_id: uuid.UUID) -> set[uuid.UUID]:
    """Notes in the project still stored only by the earlier live editor (no `content` yet)."""
    rows = await conn.execute(
        text(
            "SELECT id FROM notes WHERE project_id = :p AND deleted_at IS NULL AND content IS NULL"
        ),
        {"p": project_id},
    )
    return {r.id for r in rows}


async def get_note(conn: AsyncConnection, note_id: uuid.UUID) -> NoteRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, project_id, title, text_content, source, updated_at, version,
                       archived_at
                FROM notes WHERE id = :id AND deleted_at IS NULL
            """),
            {"id": note_id},
        )
    ).first()
    return NoteRow(**row._mapping) if row else None


async def create_note(
    conn: AsyncConnection,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    source: str = "user",
) -> uuid.UUID:
    note_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO notes (id, project_id, title, created_by, source)
            VALUES (:id, :p, :t, :u, :s)
        """),
        {"id": note_id, "p": project_id, "t": title, "u": user_id, "s": source},
    )
    return note_id


async def set_archived(conn: AsyncConnection, note_id: uuid.UUID, archived: bool) -> None:
    """Archiving hides a note from the project page; it isn't an edit, so the version stays
    (an open editor can still save)."""
    await conn.execute(
        text("""
            UPDATE notes SET archived_at = CASE WHEN :a THEN coalesce(archived_at, now()) END
            WHERE id = :id AND deleted_at IS NULL
        """),
        {"id": note_id, "a": archived},
    )


async def delete_note(conn: AsyncConnection, note_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE notes SET deleted_at = now(), updated_at = now(), version = version + 1 "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": note_id},
    )


async def load_state(conn: AsyncConnection, note_id: uuid.UUID) -> tuple[bytes | None, list[bytes]]:
    """The snapshot (if any) and the updates after it, oldest first."""
    snap = (
        await conn.execute(
            text("SELECT state, last_update_id FROM note_snapshots WHERE note_id = :n"),
            {"n": note_id},
        )
    ).first()
    after = snap.last_update_id if snap else 0
    rows = await conn.execute(
        text("SELECT update FROM note_updates WHERE note_id = :n AND id > :a ORDER BY id"),
        {"n": note_id, "a": after},
    )
    return (bytes(snap.state) if snap else None), [bytes(r[0]) for r in rows]


async def get_content(conn: AsyncConnection, note_id: uuid.UUID) -> dict[str, Any] | None:
    value = await conn.scalar(
        text("SELECT content FROM notes WHERE id = :id AND deleted_at IS NULL"), {"id": note_id}
    )
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else None


async def save(
    conn: AsyncConnection,
    note_id: uuid.UUID,
    *,
    expected_version: int | None,
    title: str,
    content: dict[str, Any],
    text_content: str,
) -> int | None:
    """Store the whole note. With `expected_version`, only if nobody saved since (else None)."""
    v = await conn.scalar(
        text("""
            UPDATE notes SET title = :t, content = CAST(:c AS jsonb), text_content = :x,
                             updated_at = now(), version = version + 1
            WHERE id = :id AND deleted_at IS NULL
              AND (CAST(:v AS integer) IS NULL OR version = :v)
            RETURNING version
        """),
        {
            "id": note_id,
            "v": expected_version,
            "t": title,
            "c": json.dumps(content),
            "x": text_content,
        },
    )
    return int(v) if v is not None else None

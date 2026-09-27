"""Queries for notes and their CRDT updates."""

import uuid
from dataclasses import dataclass
from datetime import datetime

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


async def notes_for_project(conn: AsyncConnection, project_id: uuid.UUID) -> list[NoteRow]:
    rows = await conn.execute(
        text("""
            SELECT id, project_id, title, left(text_content, 300) AS text_content, source,
                   updated_at, version
            FROM notes WHERE project_id = :p AND deleted_at IS NULL
            ORDER BY updated_at DESC LIMIT 500
        """),
        {"p": project_id},
    )
    return [NoteRow(**r._mapping) for r in rows]


async def get_note(conn: AsyncConnection, note_id: uuid.UUID) -> NoteRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, project_id, title, text_content, source, updated_at, version
                FROM notes WHERE id = :id AND deleted_at IS NULL
            """),
            {"id": note_id},
        )
    ).first()
    return NoteRow(**row._mapping) if row else None


async def create_note(
    conn: AsyncConnection, *, project_id: uuid.UUID, user_id: uuid.UUID, title: str
) -> uuid.UUID:
    note_id = uuid.uuid7()
    await conn.execute(
        text("INSERT INTO notes (id, project_id, title, created_by) VALUES (:id, :p, :t, :u)"),
        {"id": note_id, "p": project_id, "t": title, "u": user_id},
    )
    return note_id


async def update_title(
    conn: AsyncConnection, note_id: uuid.UUID, expected_version: int, title: str
) -> int | None:
    v = await conn.scalar(
        text(
            "UPDATE notes SET title = :t, updated_at = now(), version = version + 1 "
            "WHERE id = :id AND version = :v AND deleted_at IS NULL RETURNING version"
        ),
        {"id": note_id, "v": expected_version, "t": title},
    )
    return int(v) if v is not None else None


async def set_text(conn: AsyncConnection, note_id: uuid.UUID, text_content: str) -> None:
    await conn.execute(
        text(
            "UPDATE notes SET text_content = :c, updated_at = now() "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": note_id, "c": text_content},
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


async def append_update(
    conn: AsyncConnection,
    *,
    note_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    update: bytes,
    client: str = "web",
) -> None:
    await conn.execute(
        text(
            "INSERT INTO note_updates (note_id, project_id, user_id, client, update) "
            "VALUES (:n, :p, :u, :c, :b)"
        ),
        {"n": note_id, "p": project_id, "u": user_id, "c": client, "b": update},
    )
    await conn.execute(text("UPDATE notes SET updated_at = now() WHERE id = :n"), {"n": note_id})


async def notes_to_compact(conn: AsyncConnection, threshold: int) -> list[uuid.UUID]:
    rows = await conn.execute(
        text("""
            SELECT u.note_id FROM note_updates u
            LEFT JOIN note_snapshots s ON s.note_id = u.note_id
            WHERE u.id > coalesce(s.last_update_id, 0)
            GROUP BY u.note_id HAVING count(*) > :t LIMIT 100
        """),
        {"t": threshold},
    )
    return list(rows.scalars())


async def compact(
    conn: AsyncConnection, note_id: uuid.UUID, state: bytes, last_update_id: int
) -> None:
    await conn.execute(
        text("""
            INSERT INTO note_snapshots (note_id, project_id, state, last_update_id)
            SELECT id, project_id, :s, :l FROM notes WHERE id = :n
            ON CONFLICT (note_id) DO UPDATE SET state = :s, last_update_id = :l,
                                                updated_at = now()
        """),
        {"n": note_id, "s": state, "l": last_update_id},
    )
    await conn.execute(
        text("DELETE FROM note_updates WHERE note_id = :n AND id <= :l"),
        {"n": note_id, "l": last_update_id},
    )


async def last_update_id(conn: AsyncConnection, note_id: uuid.UUID) -> int:
    v = await conn.scalar(
        text("SELECT coalesce(max(id), 0) FROM note_updates WHERE note_id = :n"), {"n": note_id}
    )
    return int(v or 0)

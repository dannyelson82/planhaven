"""Queries for each person's project folders (ADR 0022). Always run as the person (RLS: own
rows only); the trigger in migration 0037 keeps folder trees sound."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class FolderRow:
    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    position: float
    created_at: datetime
    updated_at: datetime
    version: int


async def folders(conn: AsyncConnection, user_id: uuid.UUID) -> list[FolderRow]:
    rows = await conn.execute(
        text(
            "SELECT id, parent_id, name, position, created_at, updated_at, version "
            "FROM project_folders WHERE user_id = :u ORDER BY position, lower(name), id"
        ),
        {"u": user_id},
    )
    return [FolderRow(**r._mapping) for r in rows]


async def folder(conn: AsyncConnection, folder_id: uuid.UUID) -> FolderRow | None:
    row = (
        await conn.execute(
            text(
                "SELECT id, parent_id, name, position, created_at, updated_at, version "
                "FROM project_folders WHERE id = :i"
            ),
            {"i": folder_id},
        )
    ).first()
    return FolderRow(**row._mapping) if row else None


async def create(
    conn: AsyncConnection, user_id: uuid.UUID, name: str, parent_id: uuid.UUID | None
) -> uuid.UUID:
    value = await conn.scalar(
        text("""
            INSERT INTO project_folders (user_id, parent_id, name, position)
            VALUES (:u, :p, :n, coalesce((SELECT max(position) + 1 FROM project_folders
                                          WHERE user_id = :u
                                            AND parent_id IS NOT DISTINCT FROM :p), 0))
            RETURNING id
        """),
        {"u": user_id, "p": parent_id, "n": name},
    )
    if not isinstance(value, uuid.UUID):
        raise RuntimeError("folder not created")
    return value


async def update(
    conn: AsyncConnection,
    folder_id: uuid.UUID,
    *,
    name: str,
    parent_id: uuid.UUID | None,
    position: float,
) -> None:
    await conn.execute(
        text("""
            UPDATE project_folders
            SET name = :n, parent_id = :p, position = :pos, updated_at = now(),
                version = version + 1
            WHERE id = :i
        """),
        {"i": folder_id, "n": name, "p": parent_id, "pos": position},
    )


async def delete(conn: AsyncConnection, folder: FolderRow) -> None:
    """Delete a folder; what was in it moves up to its parent (projects are never deleted)."""
    await conn.execute(
        text("UPDATE project_folders SET parent_id = :p, updated_at = now() WHERE parent_id = :i"),
        {"i": folder.id, "p": folder.parent_id},
    )
    if folder.parent_id is None:
        await conn.execute(
            text("DELETE FROM project_folder_items WHERE folder_id = :i"), {"i": folder.id}
        )
    else:
        await conn.execute(
            text("UPDATE project_folder_items SET folder_id = :p WHERE folder_id = :i"),
            {"i": folder.id, "p": folder.parent_id},
        )
    await conn.execute(text("DELETE FROM project_folders WHERE id = :i"), {"i": folder.id})


async def place(
    conn: AsyncConnection, user_id: uuid.UUID, project_id: uuid.UUID, folder_id: uuid.UUID | None
) -> None:
    """Put a project in one of the person's folders, or (None) in no folder."""
    if folder_id is None:
        await conn.execute(
            text("DELETE FROM project_folder_items WHERE user_id = :u AND project_id = :p"),
            {"u": user_id, "p": project_id},
        )
        return
    await conn.execute(
        text("""
            INSERT INTO project_folder_items (user_id, project_id, folder_id)
            VALUES (:u, :p, :f)
            ON CONFLICT (user_id, project_id) DO UPDATE SET folder_id = EXCLUDED.folder_id
        """),
        {"u": user_id, "p": project_id, "f": folder_id},
    )


async def counts(conn: AsyncConnection, user_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """How many readable, not-deleted projects each folder holds directly."""
    rows = await conn.execute(
        text("""
            SELECT fi.folder_id, count(*) AS n
            FROM project_folder_items fi JOIN projects p ON p.id = fi.project_id
            WHERE fi.user_id = :u AND p.deleted_at IS NULL AND app.can_read(p.id)
            GROUP BY fi.folder_id
        """),
        {"u": user_id},
    )
    return {r.folder_id: int(r.n) for r in rows}

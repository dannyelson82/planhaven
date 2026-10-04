"""Keyword search for AI apps (ADR 0019): user transaction, so RLS shows only what the person
can see; projects marked local_ai_only are left out."""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class HitRow:
    kind: str  # project | task | note | list_item
    id: uuid.UUID
    project_id: uuid.UUID
    project_title: str
    title: str
    snippet: str


def _like(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def search(conn: AsyncConnection, query: str, limit: int) -> list[HitRow]:
    rows = await conn.execute(
        text("""
            WITH visible AS (
                SELECT id, title FROM projects
                WHERE deleted_at IS NULL AND NOT local_ai_only
            )
            SELECT * FROM (
                SELECT 'project' AS kind, p.id, p.id AS project_id, p.title AS project_title,
                       p.title, left(p.description, 200) AS snippet
                FROM projects p JOIN visible v ON v.id = p.id
                WHERE p.title ILIKE :q OR p.description ILIKE :q
                UNION ALL
                SELECT 'task', t.id, t.project_id, v.title, t.title, left(t.notes, 200)
                FROM tasks t JOIN visible v ON v.id = t.project_id
                WHERE t.deleted_at IS NULL AND (t.title ILIKE :q OR t.notes ILIKE :q)
                UNION ALL
                SELECT 'note', n.id, n.project_id, v.title, n.title, left(n.text_content, 200)
                FROM notes n JOIN visible v ON v.id = n.project_id
                WHERE n.deleted_at IS NULL AND (n.title ILIKE :q OR n.text_content ILIKE :q)
                UNION ALL
                SELECT 'list_item', i.id, i.project_id, v.title, i.text, l.title
                FROM list_items i JOIN lists l ON l.id = i.list_id AND l.deleted_at IS NULL
                JOIN visible v ON v.id = i.project_id
                WHERE i.deleted_at IS NULL AND (i.text ILIKE :q OR i.notes ILIKE :q)
            ) hits LIMIT :n
        """),
        {"q": _like(query), "n": limit},
    )
    return [HitRow(**r._mapping) for r in rows]

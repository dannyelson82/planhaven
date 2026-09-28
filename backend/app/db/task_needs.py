"""Queries for the list items a task needs."""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class NeedRow:
    task_id: uuid.UUID
    list_item_id: uuid.UUID
    text: str
    quantity: Decimal | None
    unit: str | None
    checked: bool
    list_id: uuid.UUID
    list_title: str


async def needs_for_project(conn: AsyncConnection, project_id: uuid.UUID) -> list[NeedRow]:
    rows = await conn.execute(
        text("""
            SELECT n.task_id, n.list_item_id, i.text, i.quantity, i.unit,
                   i.checked_at IS NOT NULL AS checked, l.id AS list_id, l.title AS list_title
            FROM task_needs n
            JOIN list_items i ON i.id = n.list_item_id AND i.deleted_at IS NULL
            JOIN lists l ON l.id = i.list_id AND l.deleted_at IS NULL
            WHERE n.project_id = :p
            ORDER BY l.title, i.position, i.created_at
            LIMIT 5000
        """),
        {"p": project_id},
    )
    return [NeedRow(**r._mapping) for r in rows]


async def items_in_project(
    conn: AsyncConnection, project_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    rows = await conn.execute(
        text("""
            SELECT id FROM list_items
            WHERE project_id = :p AND deleted_at IS NULL AND id = ANY(:ids)
        """),
        {"p": project_id, "ids": item_ids},
    )
    return {r[0] for r in rows}


async def set_needs(
    conn: AsyncConnection, task_id: uuid.UUID, project_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> None:
    await conn.execute(text("DELETE FROM task_needs WHERE task_id = :t"), {"t": task_id})
    for item_id in item_ids:
        await conn.execute(
            text("""
                INSERT INTO task_needs (task_id, list_item_id, project_id)
                VALUES (:t, :i, :p)
            """),
            {"t": task_id, "i": item_id, "p": project_id},
        )

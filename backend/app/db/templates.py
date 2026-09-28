"""Queries for templates (user transactions; RLS applies)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class TemplateRow:
    id: uuid.UUID
    kind: str
    list_kind: str | None
    name: str
    role: str | None
    item_count: int
    updated_at: datetime
    version: int


@dataclass(frozen=True, slots=True)
class TemplateItemRow:
    id: uuid.UUID
    template_id: uuid.UUID
    position: int
    text: str
    quantity: Decimal | None
    unit: str | None
    price_cents: int | None
    notes: str


async def role(conn: AsyncConnection, template_id: uuid.UUID) -> str | None:
    value = await conn.scalar(text("SELECT app.template_role(:t)"), {"t": template_id})
    return str(value) if value is not None else None


async def list_templates(conn: AsyncConnection) -> list[TemplateRow]:
    rows = await conn.execute(
        text("""
            SELECT t.id, t.kind, t.list_kind, t.name, app.template_role(t.id) AS role,
                   (SELECT count(*) FROM template_items i WHERE i.template_id = t.id) AS item_count,
                   t.updated_at, t.version
            FROM templates t
            ORDER BY lower(t.name) LIMIT 1000
        """)
    )
    return [TemplateRow(**r._mapping) for r in rows]


async def get_template(conn: AsyncConnection, template_id: uuid.UUID) -> TemplateRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT t.id, t.kind, t.list_kind, t.name, app.template_role(t.id) AS role,
                       (SELECT count(*) FROM template_items i
                        WHERE i.template_id = t.id) AS item_count,
                       t.updated_at, t.version
                FROM templates t
                WHERE t.id = :t
            """),
            {"t": template_id},
        )
    ).first()
    return TemplateRow(**row._mapping) if row else None


async def items(conn: AsyncConnection, template_id: uuid.UUID) -> list[TemplateItemRow]:
    rows = await conn.execute(
        text("""
            SELECT id, template_id, position, text, quantity, unit, price_cents, notes
            FROM template_items WHERE template_id = :t ORDER BY position LIMIT 1000
        """),
        {"t": template_id},
    )
    return [TemplateItemRow(**r._mapping) for r in rows]


async def get_item(conn: AsyncConnection, item_id: uuid.UUID) -> TemplateItemRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, template_id, position, text, quantity, unit, price_cents, notes
                FROM template_items WHERE id = :i
            """),
            {"i": item_id},
        )
    ).first()
    return TemplateItemRow(**row._mapping) if row else None


async def create_template(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    kind: str,
    list_kind: str | None,
    name: str,
    entries: list[dict[str, Any]],
) -> uuid.UUID:
    """The template, its creator as owner, and its items (text, quantity, unit, price_cents,
    notes) in order."""
    template_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO templates (id, kind, list_kind, name, created_by)
            VALUES (:id, :kind, :list_kind, :name, :u)
        """),
        {"id": template_id, "kind": kind, "list_kind": list_kind, "name": name, "u": user_id},
    )
    await conn.execute(
        text("INSERT INTO template_members (template_id, user_id, role) VALUES (:t, :u, 'owner')"),
        {"t": template_id, "u": user_id},
    )
    for position, entry in enumerate(entries):
        await conn.execute(
            text("""
                INSERT INTO template_items (template_id, position, text, quantity, unit,
                                            price_cents, notes)
                VALUES (:t, :pos, :text, :quantity, :unit, :price_cents, :notes)
            """),
            {"t": template_id, "pos": position, **entry},
        )
    return template_id


async def rename(
    conn: AsyncConnection, template_id: uuid.UUID, expected_version: int, name: str
) -> int | None:
    v = await conn.scalar(
        text("""
            UPDATE templates SET name = :name, updated_at = now(), version = version + 1
            WHERE id = :t AND version = :v RETURNING version
        """),
        {"t": template_id, "v": expected_version, "name": name},
    )
    return int(v) if v is not None else None


async def touch(conn: AsyncConnection, template_id: uuid.UUID) -> None:
    await conn.execute(
        text("UPDATE templates SET updated_at = now(), version = version + 1 WHERE id = :t"),
        {"t": template_id},
    )


async def delete_template(conn: AsyncConnection, template_id: uuid.UUID) -> bool:
    result = await conn.execute(text("DELETE FROM templates WHERE id = :t"), {"t": template_id})
    return result.rowcount == 1


async def delete_item(conn: AsyncConnection, item_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM template_items WHERE id = :i"), {"i": item_id})

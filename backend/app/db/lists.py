"""Queries for lists and list items (user transactions; RLS applies)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class ListRow:
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    kind: str
    open_items: int
    total_items: int
    updated_at: datetime
    version: int


@dataclass(frozen=True, slots=True)
class ItemRow:
    id: uuid.UUID
    list_id: uuid.UUID
    project_id: uuid.UUID
    text: str
    quantity: Decimal | None
    unit: str | None
    price_cents: int | None
    position: float
    checked_at: datetime | None
    updated_at: datetime
    version: int


async def lists_for_project(conn: AsyncConnection, project_id: uuid.UUID) -> list[ListRow]:
    rows = await conn.execute(
        text("""
            SELECT l.id, l.project_id, l.title, l.kind, l.updated_at, l.version,
                   count(i.id) FILTER (WHERE i.checked_at IS NULL) AS open_items,
                   count(i.id) AS total_items
            FROM lists l
            LEFT JOIN list_items i ON i.list_id = l.id AND i.deleted_at IS NULL
            WHERE l.project_id = :p AND l.deleted_at IS NULL
            GROUP BY l.id ORDER BY l.position, l.created_at
        """),
        {"p": project_id},
    )
    return [ListRow(**r._mapping) for r in rows]


async def get_list(conn: AsyncConnection, list_id: uuid.UUID) -> ListRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT l.id, l.project_id, l.title, l.kind, l.updated_at, l.version,
                       count(i.id) FILTER (WHERE i.checked_at IS NULL) AS open_items,
                       count(i.id) AS total_items
                FROM lists l
                LEFT JOIN list_items i ON i.list_id = l.id AND i.deleted_at IS NULL
                WHERE l.id = :id AND l.deleted_at IS NULL
                GROUP BY l.id
            """),
            {"id": list_id},
        )
    ).first()
    return ListRow(**row._mapping) if row else None


async def create_list(
    conn: AsyncConnection, *, project_id: uuid.UUID, user_id: uuid.UUID, title: str, kind: str
) -> uuid.UUID:
    list_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO lists (id, project_id, title, kind, created_by, position)
            VALUES (:id, :p, :t, :k, :u,
                    coalesce((SELECT max(position) + 1 FROM lists WHERE project_id = :p), 0))
        """),
        {"id": list_id, "p": project_id, "t": title, "k": kind, "u": user_id},
    )
    return list_id


async def update_list(
    conn: AsyncConnection,
    list_id: uuid.UUID,
    *,
    expected_version: int,
    title: str | None,
    kind: str | None,
) -> int | None:
    v = await conn.scalar(
        text("""
            UPDATE lists SET title = coalesce(CAST(:t AS text), title),
                             kind = coalesce(CAST(:k AS text), kind),
                             updated_at = now(), version = version + 1
            WHERE id = :id AND version = :v AND deleted_at IS NULL RETURNING version
        """),
        {"id": list_id, "v": expected_version, "t": title, "k": kind},
    )
    return int(v) if v is not None else None


async def delete_list(conn: AsyncConnection, list_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE lists SET deleted_at = now(), updated_at = now(), version = version + 1 "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": list_id},
    )


async def items(conn: AsyncConnection, list_id: uuid.UUID) -> list[ItemRow]:
    rows = await conn.execute(
        text("""
            SELECT id, list_id, project_id, text, quantity, unit, price_cents, position,
                   checked_at, updated_at, version
            FROM list_items WHERE list_id = :l AND deleted_at IS NULL
            ORDER BY checked_at IS NOT NULL, position, created_at LIMIT 2000
        """),
        {"l": list_id},
    )
    return [ItemRow(**r._mapping) for r in rows]


async def get_item(conn: AsyncConnection, item_id: uuid.UUID) -> ItemRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, list_id, project_id, text, quantity, unit, price_cents, position,
                       checked_at, updated_at, version
                FROM list_items WHERE id = :id AND deleted_at IS NULL
            """),
            {"id": item_id},
        )
    ).first()
    return ItemRow(**row._mapping) if row else None


async def create_item(
    conn: AsyncConnection,
    *,
    item_id: uuid.UUID,
    list_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    text_: str,
    quantity: Decimal | None,
    unit: str | None,
    price_cents: int | None,
) -> None:
    await conn.execute(
        text("""
            INSERT INTO list_items (id, list_id, project_id, text, quantity, unit, price_cents,
                                    created_by, position)
            VALUES (:id, :l, :p, :t, :q, :unit, :price, :u,
                    coalesce((SELECT max(position) + 1 FROM list_items WHERE list_id = :l), 0))
        """),
        {
            "id": item_id,
            "l": list_id,
            "p": project_id,
            "t": text_,
            "q": quantity,
            "unit": unit,
            "price": price_cents,
            "u": user_id,
        },
    )


async def update_item(
    conn: AsyncConnection,
    item_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    expected_version: int | None,
    text_: str | None,
    quantity: Decimal | None,
    set_quantity: bool,
    unit: str | None,
    set_unit: bool,
    price_cents: int | None,
    set_price: bool,
    checked: bool | None,
) -> int | None:
    """expected_version None = unconditional (only allowed for check-offs by the service)."""
    v = await conn.scalar(
        text("""
            UPDATE list_items SET
                text = coalesce(CAST(:t AS text), text),
                quantity = CASE WHEN CAST(:set_q AS boolean)
                                THEN CAST(:q AS numeric) ELSE quantity END,
                unit = CASE WHEN CAST(:set_unit AS boolean)
                            THEN CAST(:unit AS text) ELSE unit END,
                price_cents = CASE WHEN CAST(:set_price AS boolean)
                                   THEN CAST(:price AS bigint) ELSE price_cents END,
                checked_at = CASE WHEN CAST(:c AS boolean) IS NULL THEN checked_at
                                  WHEN CAST(:c AS boolean) THEN coalesce(checked_at, now())
                                  ELSE NULL END,
                checked_by = CASE WHEN CAST(:c AS boolean) IS NULL THEN checked_by
                                  WHEN CAST(:c AS boolean)
                                  THEN coalesce(checked_by, CAST(:u AS uuid))
                                  ELSE NULL END,
                updated_at = now(), version = version + 1
            WHERE id = :id AND deleted_at IS NULL
              AND (CAST(:v AS integer) IS NULL OR version = CAST(:v AS integer))
            RETURNING version
        """),
        {
            "id": item_id,
            "v": expected_version,
            "t": text_,
            "q": quantity,
            "set_q": set_quantity,
            "unit": unit,
            "set_unit": set_unit,
            "price": price_cents,
            "set_price": set_price,
            "c": checked,
            "u": user_id,
        },
    )
    return int(v) if v is not None else None


async def delete_item(conn: AsyncConnection, item_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE list_items SET deleted_at = now(), updated_at = now(), "
            "version = version + 1 WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": item_id},
    )


async def remembered(
    conn: AsyncConnection, user_id: uuid.UUID, key: str, scope: str
) -> uuid.UUID | None:
    value = await conn.scalar(
        text(
            "SELECT resource_id FROM idempotency_keys WHERE user_id = :u AND key = :k "
            "AND scope = :s"
        ),
        {"u": user_id, "k": key, "s": scope},
    )
    return value if isinstance(value, uuid.UUID) else None


async def remember(
    conn: AsyncConnection, user_id: uuid.UUID, key: str, scope: str, resource_id: uuid.UUID
) -> None:
    await conn.execute(
        text(
            "INSERT INTO idempotency_keys (user_id, key, scope, resource_id) "
            "VALUES (:u, :k, :s, :r)"
        ),
        {"u": user_id, "k": key, "s": scope, "r": resource_id},
    )

"""Queries for quotes and cost entries on a project."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class QuoteRow:
    id: uuid.UUID
    project_id: uuid.UUID
    project_title: str
    title: str
    amount_cents: int | None
    status: str
    notes: str
    contact_id: uuid.UUID | None
    # Filled only when this user can see the contact.
    contact_name: str | None
    attachment_id: uuid.UUID | None
    attachment_name: str | None
    updated_at: datetime
    version: int


@dataclass(frozen=True, slots=True)
class CostRow:
    id: uuid.UUID
    project_id: uuid.UUID
    description: str
    amount_cents: int
    spent_on: date
    quote_id: uuid.UUID | None
    created_at: datetime
    store: str = ""
    receipt_id: uuid.UUID | None = None
    receipt_name: str | None = None
    item_count: int = 0
    version: int = 1


@dataclass(frozen=True, slots=True)
class CostItemRow:
    id: uuid.UUID
    cost_id: uuid.UUID
    project_id: uuid.UUID
    text: str
    quantity: Decimal | None
    price_cents: int | None
    list_item_id: uuid.UUID | None
    version: int


async def quotes_for_project(conn: AsyncConnection, project_id: uuid.UUID) -> list[QuoteRow]:
    rows = await conn.execute(
        text("""
            SELECT q.id, q.project_id, p.title AS project_title, q.title, q.amount_cents,
                   q.status, q.notes, q.contact_id, c.name AS contact_name, q.attachment_id,
                   a.filename AS attachment_name, q.updated_at, q.version
            FROM quotes q
            JOIN projects p ON p.id = q.project_id AND p.deleted_at IS NULL
            LEFT JOIN contacts c ON c.id = q.contact_id AND c.deleted_at IS NULL
            LEFT JOIN attachments a ON a.id = q.attachment_id AND a.deleted_at IS NULL
            WHERE q.project_id = :p AND q.deleted_at IS NULL ORDER BY q.created_at LIMIT 500
        """),
        {"p": project_id},
    )
    return [QuoteRow(**r._mapping) for r in rows]


async def quotes_for_contact(conn: AsyncConnection, contact_id: uuid.UUID) -> list[QuoteRow]:
    """Quotes from this contact on projects this user can see (RLS)."""
    rows = await conn.execute(
        text("""
            SELECT q.id, q.project_id, p.title AS project_title, q.title, q.amount_cents,
                   q.status, q.notes, q.contact_id, c.name AS contact_name, q.attachment_id,
                   a.filename AS attachment_name, q.updated_at, q.version
            FROM quotes q
            JOIN projects p ON p.id = q.project_id AND p.deleted_at IS NULL
            LEFT JOIN contacts c ON c.id = q.contact_id AND c.deleted_at IS NULL
            LEFT JOIN attachments a ON a.id = q.attachment_id AND a.deleted_at IS NULL
            WHERE q.contact_id = :c AND q.deleted_at IS NULL
            ORDER BY q.updated_at DESC LIMIT 500
        """),
        {"c": contact_id},
    )
    return [QuoteRow(**r._mapping) for r in rows]


async def get_quote(conn: AsyncConnection, quote_id: uuid.UUID) -> QuoteRow | None:
    row = (
        await conn.execute(
            text("""
            SELECT q.id, q.project_id, p.title AS project_title, q.title, q.amount_cents,
                   q.status, q.notes, q.contact_id, c.name AS contact_name, q.attachment_id,
                   a.filename AS attachment_name, q.updated_at, q.version
            FROM quotes q
            JOIN projects p ON p.id = q.project_id AND p.deleted_at IS NULL
            LEFT JOIN contacts c ON c.id = q.contact_id AND c.deleted_at IS NULL
            LEFT JOIN attachments a ON a.id = q.attachment_id AND a.deleted_at IS NULL
            WHERE q.id = :id AND q.deleted_at IS NULL
        """),
            {"id": quote_id},
        )
    ).first()
    return QuoteRow(**row._mapping) if row else None


async def create_quote(
    conn: AsyncConnection, *, project_id: uuid.UUID, user_id: uuid.UUID, values: dict[str, Any]
) -> uuid.UUID:
    quote_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO quotes (id, project_id, contact_id, title, amount_cents, status,
                                attachment_id, notes, created_by)
            VALUES (:id, :p, :contact_id, :title, :amount_cents, :status, :attachment_id,
                    :notes, :u)
        """),
        {"id": quote_id, "p": project_id, "u": user_id, **values},
    )
    return quote_id


async def update_quote(
    conn: AsyncConnection, quote_id: uuid.UUID, expected_version: int, values: dict[str, Any]
) -> int | None:
    v = await conn.scalar(
        text("""
            UPDATE quotes SET contact_id = :contact_id, title = :title,
                              amount_cents = :amount_cents, status = :status,
                              attachment_id = :attachment_id, notes = :notes,
                              updated_at = now(), version = version + 1
            WHERE id = :id AND version = :v AND deleted_at IS NULL RETURNING version
        """),
        {"id": quote_id, "v": expected_version, **values},
    )
    return int(v) if v is not None else None


async def delete_quote(conn: AsyncConnection, quote_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE quotes SET deleted_at = now(), updated_at = now(), version = version + 1 "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": quote_id},
    )


async def costs_for_project(conn: AsyncConnection, project_id: uuid.UUID) -> list[CostRow]:
    rows = await conn.execute(
        text("""
            SELECT c.id, c.project_id, c.description, c.amount_cents, c.spent_on, c.quote_id,
                   c.created_at, c.store, c.receipt_id, a.filename AS receipt_name,
                   (SELECT count(*) FROM cost_items i WHERE i.cost_id = c.id) AS item_count,
                   c.version
            FROM cost_entries c
            LEFT JOIN attachments a ON a.id = c.receipt_id AND a.deleted_at IS NULL
            WHERE c.project_id = :p AND c.deleted_at IS NULL
            ORDER BY c.spent_on DESC, c.created_at DESC LIMIT 1000
        """),
        {"p": project_id},
    )
    return [CostRow(**r._mapping) for r in rows]


async def get_cost(conn: AsyncConnection, cost_id: uuid.UUID) -> CostRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT c.id, c.project_id, c.description, c.amount_cents, c.spent_on, c.quote_id,
                       c.created_at, c.store, c.receipt_id, a.filename AS receipt_name,
                       (SELECT count(*) FROM cost_items i WHERE i.cost_id = c.id) AS item_count,
                       c.version
                FROM cost_entries c
                LEFT JOIN attachments a ON a.id = c.receipt_id AND a.deleted_at IS NULL
                WHERE c.id = :id AND c.deleted_at IS NULL
            """),
            {"id": cost_id},
        )
    ).first()
    return CostRow(**row._mapping) if row else None


async def create_cost(
    conn: AsyncConnection, *, project_id: uuid.UUID, user_id: uuid.UUID, values: dict[str, Any]
) -> uuid.UUID:
    cost_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO cost_entries (id, project_id, description, amount_cents, spent_on,
                                      quote_id, created_by)
            VALUES (:id, :p, :description, :amount_cents, COALESCE(:spent_on, current_date),
                    :quote_id, :u)
        """),
        {"id": cost_id, "p": project_id, "u": user_id, **values},
    )
    return cost_id


async def update_cost(
    conn: AsyncConnection, cost_id: uuid.UUID, expected_version: int, values: dict[str, Any]
) -> int | None:
    v = await conn.scalar(
        text("""
            UPDATE cost_entries SET description = :description, amount_cents = :amount_cents,
                                    spent_on = :spent_on, quote_id = :quote_id, store = :store,
                                    receipt_id = :receipt_id,
                                    updated_at = now(), version = version + 1
            WHERE id = :id AND version = :v AND deleted_at IS NULL RETURNING version
        """),
        {"id": cost_id, "v": expected_version, **values},
    )
    return int(v) if v is not None else None


async def delete_cost(conn: AsyncConnection, cost_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE cost_entries SET deleted_at = now(), updated_at = now(), "
            "version = version + 1 WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": cost_id},
    )


async def attachment_in_project(
    conn: AsyncConnection, attachment_id: uuid.UUID, project_id: uuid.UUID
) -> bool:
    return bool(
        await conn.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM attachments WHERE id = :a AND project_id = :p "
                "AND deleted_at IS NULL)"
            ),
            {"a": attachment_id, "p": project_id},
        )
    )


async def quote_in_project(
    conn: AsyncConnection, quote_id: uuid.UUID, project_id: uuid.UUID
) -> bool:
    return bool(
        await conn.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM quotes WHERE id = :q AND project_id = :p "
                "AND deleted_at IS NULL)"
            ),
            {"q": quote_id, "p": project_id},
        )
    )


# ---------------------------------------------------------------- purchase items

MAX_ITEMS = 500


async def items_for_cost(conn: AsyncConnection, cost_id: uuid.UUID) -> list[CostItemRow]:
    rows = await conn.execute(
        text(
            "SELECT id, cost_id, project_id, text, quantity, price_cents, list_item_id, version "
            "FROM cost_items WHERE cost_id = :c ORDER BY created_at, id LIMIT 500"
        ),
        {"c": cost_id},
    )
    return [CostItemRow(**r._mapping) for r in rows]


async def count_items(conn: AsyncConnection, cost_id: uuid.UUID) -> int:
    return int(
        await conn.scalar(
            text("SELECT count(*) FROM cost_items WHERE cost_id = :c"), {"c": cost_id}
        )
        or 0
    )


async def get_item(conn: AsyncConnection, item_id: uuid.UUID) -> CostItemRow | None:
    row = (
        await conn.execute(
            text(
                "SELECT id, cost_id, project_id, text, quantity, price_cents, list_item_id, "
                "version FROM cost_items WHERE id = :id"
            ),
            {"id": item_id},
        )
    ).first()
    return CostItemRow(**row._mapping) if row else None


async def create_item(
    conn: AsyncConnection,
    *,
    cost: CostRow,
    user_id: uuid.UUID,
    text_value: str,
    quantity: Decimal | None,
    price_cents: int | None,
    list_item_id: uuid.UUID | None = None,
) -> uuid.UUID:
    item_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO cost_items (id, cost_id, project_id, text, quantity, price_cents,
                                    list_item_id, created_by)
            VALUES (:id, :c, :p, :t, :q, :price, :li, :u)
        """),
        {
            "id": item_id,
            "c": cost.id,
            "p": cost.project_id,
            "t": text_value,
            "q": quantity,
            "price": price_cents,
            "li": list_item_id,
            "u": user_id,
        },
    )
    return item_id


async def update_item(
    conn: AsyncConnection, item_id: uuid.UUID, expected_version: int, values: dict[str, Any]
) -> int | None:
    v = await conn.scalar(
        text("""
            UPDATE cost_items SET text = :text, quantity = :quantity, price_cents = :price_cents,
                                  updated_at = now(), version = version + 1
            WHERE id = :id AND version = :v RETURNING version
        """),
        {"id": item_id, "v": expected_version, **values},
    )
    return int(v) if v is not None else None


async def delete_item(conn: AsyncConnection, item_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM cost_items WHERE id = :id"), {"id": item_id})


async def list_items_in_project(
    conn: AsyncConnection, item_ids: list[uuid.UUID], project_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, Decimal | None, int | None]]:
    """(id, text, quantity, price) of these list items, if they're in the project."""
    rows = await conn.execute(
        text("""
            SELECT id, text, quantity, price_cents FROM list_items
            WHERE id = ANY(:ids) AND project_id = :p AND deleted_at IS NULL
            ORDER BY position, created_at
        """),
        {"ids": item_ids, "p": project_id},
    )
    return [(r.id, r.text, r.quantity, r.price_cents) for r in rows]

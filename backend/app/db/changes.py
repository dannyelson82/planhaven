"""Queries for the change feed (ADR 0021, migration 0036).

`changes` is system-only and holds no content: `entries` reads it for one person, limited to
the scopes they belong to now. Items themselves are read as the person (RLS) by `rows`, with
one fixed statement per kind; no SQL is built from input.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Kind -> its rows as the person sees them now (RLS), without trash and without internals.
_NOT_DELETED = "deleted_at IS NULL"
_ROWS: dict[str, str] = {
    "projects": "SELECT id, to_jsonb(t) - 'deleted_at' AS data FROM projects t",
    "tasks": "SELECT id, to_jsonb(t) - 'deleted_at' AS data FROM tasks t",
    "lists": "SELECT id, to_jsonb(t) - 'deleted_at' AS data FROM lists t",
    "list_items": "SELECT id, to_jsonb(t) - 'deleted_at' AS data FROM list_items t",
    "notes": "SELECT id, to_jsonb(t) - 'deleted_at' - 'content' AS data FROM notes t",
    "attachments": "SELECT id, to_jsonb(t) - 'deleted_at' - 'blob_sha256' AS data "
    "FROM attachments t",
    "quotes": "SELECT id, to_jsonb(t) - 'deleted_at' AS data FROM quotes t",
    "cost_entries": "SELECT id, to_jsonb(t) - 'deleted_at' AS data FROM cost_entries t",
    "assets": "SELECT id, to_jsonb(t) - 'deleted_at' AS data FROM assets t",
    "asset_readings": "SELECT id, to_jsonb(t) AS data FROM asset_readings t",
    "service_schedules": "SELECT id, to_jsonb(t) - 'deleted_at' AS data FROM service_schedules t",
    "service_records": "SELECT id, to_jsonb(t) - 'deleted_at' AS data FROM service_records t",
    "contacts": "SELECT id, to_jsonb(t) - 'deleted_at' AS data FROM contacts t",
}
KINDS: tuple[str, ...] = tuple(_ROWS)
# Which scope column each kind has (for a snapshot of one project, asset or contact).
SCOPE: dict[str, dict[str, str]] = {
    "project": {
        "projects": "id",
        "tasks": "project_id",
        "lists": "project_id",
        "list_items": "project_id",
        "notes": "project_id",
        "attachments": "project_id",
        "quotes": "project_id",
        "cost_entries": "project_id",
    },
    "asset": {
        "assets": "id",
        "asset_readings": "asset_id",
        "service_schedules": "asset_id",
        "service_records": "asset_id",
    },
    "contact": {"contacts": "id"},
}
_HAS_TRASH = {k for k in KINDS if k != "asset_readings"}


def _statement(kind: str, where: list[str], order_limit: bool) -> str:
    """One of a fixed set of statements: the kind and the clauses come from the constants
    above, values are always bound parameters."""
    clauses = list(where)
    if kind in _HAS_TRASH:
        clauses.append(_NOT_DELETED)
    sql = _ROWS[kind] + " WHERE " + " AND ".join(clauses)
    if order_limit:
        sql += " ORDER BY id LIMIT :n"
    return sql


async def rows(conn: AsyncConnection, kind: str, ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
    """The current, visible, not-deleted rows of one kind, by id (run as the person)."""
    if kind not in _ROWS or not ids:
        return {}
    result = await conn.execute(text(_statement(kind, ["id = ANY(:ids)"], False)), {"ids": ids})
    return {r.id: r.data for r in result}


async def page(
    conn: AsyncConnection,
    kind: str,
    after: uuid.UUID,
    limit: int,
    scope: tuple[str, uuid.UUID] | None,
) -> list[tuple[uuid.UUID, Any]]:
    """A snapshot page of one kind (run as the person), in id order after `after`."""
    where = ["id > :after"]
    params: dict[str, Any] = {"after": after, "n": limit}
    if scope is not None:
        column = SCOPE[scope[0]].get(kind)
        if column is None:
            return []
        where.append(f"{column} = :scope")
        params["scope"] = scope[1]
    result = await conn.execute(text(_statement(kind, where, True)), params)
    return [(r.id, r.data) for r in result]


@dataclass(frozen=True, slots=True)
class Entry:
    id: int
    txid: int
    kind: str
    item_id: uuid.UUID
    op: str
    project_id: uuid.UUID | None
    asset_id: uuid.UUID | None
    contact_id: uuid.UUID | None


async def entries(
    conn: AsyncConnection, user_id: uuid.UUID, after: tuple[int, int], limit: int
) -> list[Entry]:
    """Changes after the cursor in scopes the person belongs to now, plus their own access
    changes (system context, filtered here). Only transactions older than every running one
    are returned, so nothing can appear later before a cursor already handed out."""
    result = await conn.execute(
        text("""
            SELECT c.id, c.txid::text::bigint AS txid, c.kind, c.item_id, c.op,
                   c.project_id, c.asset_id, c.contact_id
            FROM changes c
            WHERE (c.txid, c.id) > (CAST(CAST(:tx AS text) AS xid8), :id)
              AND c.txid < pg_snapshot_xmin(pg_current_snapshot())
              AND (c.user_id = :u
                   OR c.project_id IN (SELECT project_id FROM project_members WHERE user_id = :u)
                   OR c.asset_id IN (SELECT asset_id FROM asset_members WHERE user_id = :u)
                   OR c.contact_id IN (SELECT contact_id FROM contact_members WHERE user_id = :u))
            ORDER BY c.txid, c.id
            LIMIT :n
        """),
        {"tx": str(after[0]), "id": after[1], "u": user_id, "n": limit},
    )
    return [Entry(**r._mapping) for r in result]


async def watermark(conn: AsyncConnection) -> int:
    """Where a feed starts after a snapshot taken now: every transaction from here on is
    replayed (the snapshot already holds what finished before)."""
    value = await conn.scalar(text("SELECT pg_snapshot_xmin(pg_current_snapshot())::text"))
    return int(str(value))


async def purged_through(conn: AsyncConnection) -> int:
    value = await conn.scalar(text("SELECT txid::text FROM changes_purged"))
    return int(str(value)) if value is not None else 0


async def purge(conn: AsyncConnection, days: int = 30) -> None:
    """Housekeeping: drop changes older than `days`, remembering how far (system context)."""
    newest = await conn.scalar(
        text("""
            WITH gone AS (
                DELETE FROM changes WHERE created_at < now() - make_interval(days => :d)
                RETURNING txid
            )
            SELECT max(txid)::text FROM gone
        """),
        {"d": days},
    )
    if newest is not None:
        await conn.execute(
            text("""
                INSERT INTO changes_purged (txid) VALUES (CAST(CAST(:t AS text) AS xid8))
                ON CONFLICT (only_row) DO UPDATE SET txid = greatest(changes_purged.txid,
                                                                      EXCLUDED.txid)
            """),
            {"t": str(newest)},
        )

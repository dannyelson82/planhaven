"""Queries for experimental features: the admin's choices (system context) and each person's
opt-ins (their own rows only)."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def availability(conn: AsyncConnection) -> dict[str, bool]:
    """System context: the master switch and each feature's availability, as set."""
    rows = await conn.execute(text("SELECT name, available FROM experiments"))
    return {r.name: bool(r.available) for r in rows}


async def set_available(
    conn: AsyncConnection, name: str, available: bool, user_id: uuid.UUID
) -> None:
    await conn.execute(
        text("""
            INSERT INTO experiments (name, available, changed_by) VALUES (:n, :a, :u)
            ON CONFLICT (name) DO UPDATE
            SET available = EXCLUDED.available, changed_by = EXCLUDED.changed_by,
                changed_at = now()
        """),
        {"n": name, "a": available, "u": user_id},
    )


async def optins(conn: AsyncConnection) -> set[str]:
    rows = await conn.execute(
        text("SELECT name FROM experiment_optins WHERE user_id = app.current_user_id()")
    )
    return {r.name for r in rows}


async def set_optin(conn: AsyncConnection, name: str, on: bool) -> None:
    if on:
        await conn.execute(
            text(
                "INSERT INTO experiment_optins (user_id, name) VALUES (app.current_user_id(), :n) "
                "ON CONFLICT DO NOTHING"
            ),
            {"n": name},
        )
    else:
        await conn.execute(
            text(
                "DELETE FROM experiment_optins WHERE user_id = app.current_user_id() AND name = :n"
            ),
            {"n": name},
        )

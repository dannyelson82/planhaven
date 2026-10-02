"""Queries for the welcome tour and "What's new" state (own row; RLS)."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class OnboardingRow:
    welcome_done_at: datetime | None
    whats_new_seen: str | None


async def get(conn: AsyncConnection, user_id: uuid.UUID) -> OnboardingRow | None:
    row = (
        await conn.execute(
            text("SELECT welcome_done_at, whats_new_seen FROM onboarding WHERE user_id = :u"),
            {"u": user_id},
        )
    ).first()
    return OnboardingRow(**row._mapping) if row else None


async def put(
    conn: AsyncConnection, user_id: uuid.UUID, *, welcome_done: bool | None, seen: str | None
) -> None:
    """Record the welcome tour as done, and/or the latest "What's new" seen (never older)."""
    await conn.execute(
        text("""
            INSERT INTO onboarding (user_id, welcome_done_at, whats_new_seen)
            VALUES (:u, CASE WHEN :w THEN now() END, :s)
            ON CONFLICT (user_id) DO UPDATE SET
                welcome_done_at = CASE WHEN :w THEN coalesce(onboarding.welcome_done_at, now())
                                       ELSE onboarding.welcome_done_at END,
                whats_new_seen = coalesce(EXCLUDED.whats_new_seen, onboarding.whats_new_seen),
                updated_at = now()
        """),
        {"u": user_id, "w": bool(welcome_done), "s": seen},
    )


async def member_since(conn: AsyncConnection, user_id: uuid.UUID) -> datetime | None:
    value = await conn.scalar(text("SELECT created_at FROM users WHERE id = :u"), {"u": user_id})
    return value if isinstance(value, datetime) else None

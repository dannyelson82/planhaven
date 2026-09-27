"""Queries for second factors and session assurance state."""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class TotpRow:
    secret_encrypted: bytes
    confirmed: bool
    last_used_step: int | None


async def totp_for(conn: AsyncConnection, user_id: uuid.UUID, *, confirmed: bool) -> TotpRow | None:
    """The user's confirmed TOTP secret, or the pending one being set up."""
    row = (
        await conn.execute(
            text(
                "SELECT secret_encrypted, confirmed_at IS NOT NULL AS confirmed, "
                "last_used_step FROM totp_credentials "
                "WHERE user_id = :u AND (confirmed_at IS NOT NULL) = :confirmed"
            ),
            {"u": user_id, "confirmed": confirmed},
        )
    ).first()
    return TotpRow(bytes(row.secret_encrypted), row.confirmed, row.last_used_step) if row else None


async def save_pending_totp(conn: AsyncConnection, user_id: uuid.UUID, secret: bytes) -> None:
    """Store a new, unconfirmed secret, replacing any earlier unconfirmed one."""
    await conn.execute(
        text("DELETE FROM totp_credentials WHERE user_id = :u AND confirmed_at IS NULL"),
        {"u": user_id},
    )
    await conn.execute(
        text("INSERT INTO totp_credentials (user_id, secret_encrypted) VALUES (:u, :s)"),
        {"u": user_id, "s": secret},
    )


async def confirm_totp(conn: AsyncConnection, user_id: uuid.UUID, step: int) -> None:
    """Make the pending secret the user's TOTP factor, replacing any earlier one."""
    await conn.execute(
        text("DELETE FROM totp_credentials WHERE user_id = :u AND confirmed_at IS NOT NULL"),
        {"u": user_id},
    )
    await conn.execute(
        text(
            "UPDATE totp_credentials SET confirmed_at = now(), last_used_step = :step "
            "WHERE user_id = :u AND confirmed_at IS NULL"
        ),
        {"u": user_id, "step": step},
    )


async def use_totp_step(conn: AsyncConnection, user_id: uuid.UUID, step: int) -> bool:
    """Record a used time step. False if it (or a later one) was already used: a code can't be
    replayed, even within its validity window."""
    result = await conn.execute(
        text(
            "UPDATE totp_credentials SET last_used_step = :step WHERE user_id = :u "
            "AND confirmed_at IS NOT NULL "
            "AND (last_used_step IS NULL OR last_used_step < :step)"
        ),
        {"u": user_id, "step": step},
    )
    return result.rowcount == 1


async def replace_recovery_codes(
    conn: AsyncConnection, user_id: uuid.UUID, code_hashes: list[bytes]
) -> None:
    await conn.execute(text("DELETE FROM recovery_codes WHERE user_id = :u"), {"u": user_id})
    for code_hash in code_hashes:
        await conn.execute(
            text("INSERT INTO recovery_codes (user_id, code_hash) VALUES (:u, :h)"),
            {"u": user_id, "h": code_hash},
        )


async def use_recovery_code(conn: AsyncConnection, user_id: uuid.UUID, code_hash: bytes) -> bool:
    result = await conn.execute(
        text(
            "UPDATE recovery_codes SET used_at = now() WHERE user_id = :u "
            "AND code_hash = :h AND used_at IS NULL"
        ),
        {"u": user_id, "h": code_hash},
    )
    return result.rowcount == 1


async def remaining_recovery_codes(conn: AsyncConnection, user_id: uuid.UUID) -> int:
    count = await conn.scalar(
        text("SELECT count(*) FROM recovery_codes WHERE user_id = :u AND used_at IS NULL"),
        {"u": user_id},
    )
    return int(count or 0)


async def has_second_factor(conn: AsyncConnection, user_id: uuid.UUID) -> bool:
    return bool(
        await conn.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM totp_credentials "
                "WHERE user_id = :u AND confirmed_at IS NOT NULL)"
            ),
            {"u": user_id},
        )
    )


async def mark_session_verified(conn: AsyncConnection, session_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE sessions SET mfa_verified = true, reauth_at = now(), mfa_failures = 0 "
            "WHERE id = :id"
        ),
        {"id": session_id},
    )


async def record_mfa_failure(conn: AsyncConnection, session_id: uuid.UUID) -> int:
    failures = await conn.scalar(
        text(
            "UPDATE sessions SET mfa_failures = mfa_failures + 1 WHERE id = :id "
            "RETURNING mfa_failures"
        ),
        {"id": session_id},
    )
    return int(failures or 0)

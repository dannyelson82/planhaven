"""Queries for invites, notifications and admin account management (system context unless
noted)."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# ---------------------------------------------------------------- invites


@dataclass(frozen=True, slots=True)
class InviteRow:
    id: uuid.UUID
    email: str | None
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None


async def create_invite(
    conn: AsyncConnection,
    *,
    token_hash: bytes,
    email: str | None,
    created_by: uuid.UUID,
    ttl: timedelta,
) -> uuid.UUID:
    invite_id = uuid.uuid7()
    await conn.execute(
        text(
            "INSERT INTO invites (id, token_hash, email, created_by, expires_at) "
            "VALUES (:id, :h, :e, :by, now() + :ttl)"
        ),
        {"id": invite_id, "h": token_hash, "e": email, "by": created_by, "ttl": ttl},
    )
    return invite_id


async def valid_invite(conn: AsyncConnection, token_hash: bytes) -> InviteRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, email, created_at, expires_at, used_at, revoked_at FROM invites
                WHERE token_hash = :h AND used_at IS NULL AND revoked_at IS NULL
                  AND expires_at > now()
            """),
            {"h": token_hash},
        )
    ).first()
    return InviteRow(**row._mapping) if row else None


async def consume_invite(conn: AsyncConnection, invite_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    result = await conn.execute(
        text(
            "UPDATE invites SET used_at = now(), used_by = :u WHERE id = :id "
            "AND used_at IS NULL AND revoked_at IS NULL AND expires_at > now()"
        ),
        {"id": invite_id, "u": user_id},
    )
    return result.rowcount == 1


async def list_invites(conn: AsyncConnection) -> list[InviteRow]:
    rows = await conn.execute(
        text("""
            SELECT id, email, created_at, expires_at, used_at, revoked_at FROM invites
            WHERE created_at > now() - interval '30 days' ORDER BY created_at DESC LIMIT 200
        """)
    )
    return [InviteRow(**r._mapping) for r in rows]


async def revoke_invite(conn: AsyncConnection, invite_id: uuid.UUID) -> bool:
    result = await conn.execute(
        text(
            "UPDATE invites SET revoked_at = now() WHERE id = :id "
            "AND used_at IS NULL AND revoked_at IS NULL"
        ),
        {"id": invite_id},
    )
    return result.rowcount == 1


# ---------------------------------------------------------------- users (admin view)


@dataclass(frozen=True, slots=True)
class UserSummary:
    id: uuid.UUID
    email: str
    display_name: str
    is_admin: bool
    disabled: bool
    created_at: datetime
    has_second_factor: bool
    last_seen_at: datetime | None


async def list_users(conn: AsyncConnection) -> list[UserSummary]:
    rows = await conn.execute(
        text("""
            SELECT u.id, u.email, u.display_name, u.is_admin,
                   u.disabled_at IS NOT NULL AS disabled, u.created_at,
                   (EXISTS (SELECT 1 FROM totp_credentials t
                            WHERE t.user_id = u.id AND t.confirmed_at IS NOT NULL)
                    OR EXISTS (SELECT 1 FROM webauthn_credentials w WHERE w.user_id = u.id))
                     AS has_second_factor,
                   (SELECT max(s.last_seen_at) FROM sessions s WHERE s.user_id = u.id)
                     AS last_seen_at
            FROM users u ORDER BY u.created_at LIMIT 1000
        """)
    )
    return [UserSummary(**r._mapping) for r in rows]


async def admin_count(conn: AsyncConnection) -> int:
    n = await conn.scalar(text("SELECT count(*) FROM users WHERE is_admin AND disabled_at IS NULL"))
    return int(n or 0)


async def set_disabled(conn: AsyncConnection, user_id: uuid.UUID, disabled: bool) -> bool:
    result = await conn.execute(
        text(
            "UPDATE users SET disabled_at = CASE WHEN :d THEN now() END, updated_at = now(), "
            "version = version + 1 WHERE id = :id"
        ),
        {"id": user_id, "d": disabled},
    )
    return result.rowcount == 1


async def set_admin(conn: AsyncConnection, user_id: uuid.UUID, is_admin: bool) -> bool:
    result = await conn.execute(
        text(
            "UPDATE users SET is_admin = :a, updated_at = now(), version = version + 1 "
            "WHERE id = :id"
        ),
        {"id": user_id, "a": is_admin},
    )
    return result.rowcount == 1


async def reset_second_factors(conn: AsyncConnection, user_id: uuid.UUID) -> None:
    params = {"u": user_id}
    await conn.execute(text("DELETE FROM totp_credentials WHERE user_id = :u"), params)
    await conn.execute(text("DELETE FROM webauthn_credentials WHERE user_id = :u"), params)
    await conn.execute(text("DELETE FROM recovery_codes WHERE user_id = :u"), params)


async def revoke_all_sessions(conn: AsyncConnection, user_id: uuid.UUID) -> None:
    await conn.execute(
        text("UPDATE sessions SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL"),
        {"u": user_id},
    )


# ---------------------------------------------------------------- notifications


@dataclass(frozen=True, slots=True)
class NotificationRow:
    id: uuid.UUID
    kind: str
    data: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


async def notify(
    conn: AsyncConnection, user_id: uuid.UUID, kind: str, data: dict[str, Any]
) -> None:
    await conn.execute(
        text("INSERT INTO notifications (user_id, kind, data) VALUES (:u, :k, CAST(:d AS jsonb))"),
        {"u": user_id, "k": kind, "d": json.dumps(data)},
    )


async def own_notifications(conn: AsyncConnection, user_id: uuid.UUID) -> list[NotificationRow]:
    rows = await conn.execute(
        text(
            "SELECT id, kind, data, created_at, read_at FROM notifications "
            "WHERE user_id = :u ORDER BY created_at DESC LIMIT 100"
        ),
        {"u": user_id},
    )
    return [NotificationRow(**r._mapping) for r in rows]


async def mark_read(conn: AsyncConnection, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
    result = await conn.execute(
        text(
            "UPDATE notifications SET read_at = now() WHERE id = :id AND user_id = :u "
            "AND read_at IS NULL"
        ),
        {"id": notification_id, "u": user_id},
    )
    return result.rowcount == 1


async def seen_ip_recently(
    conn: AsyncConnection, user_id: uuid.UUID, ip: str | None, exclude_session: uuid.UUID | None
) -> bool:
    if ip is None:
        return True
    return bool(
        await conn.scalar(
            text("""
                SELECT EXISTS (SELECT 1 FROM sessions WHERE user_id = :u
                               AND ip = CAST(:ip AS inet)
                               AND created_at > now() - interval '30 days'
                               AND (CAST(:x AS uuid) IS NULL OR id <> :x))
            """),
            {"u": user_id, "ip": ip, "x": exclude_session},
        )
    )


# ---------------------------------------------------------------- password reset links


@dataclass(frozen=True, slots=True)
class ResetRow:
    id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime


async def create_password_reset(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    token_hash: bytes,
    created_by: uuid.UUID,
    ttl: timedelta,
) -> ResetRow:
    """System context. Cancels this person's older unused links."""
    await conn.execute(
        text(
            "UPDATE password_resets SET revoked_at = now() WHERE user_id = :u "
            "AND used_at IS NULL AND revoked_at IS NULL"
        ),
        {"u": user_id},
    )
    reset_id = uuid.uuid7()
    row = (
        await conn.execute(
            text("""
                INSERT INTO password_resets (id, user_id, token_hash, created_by, expires_at)
                VALUES (:id, :u, :h, :by, now() + :ttl)
                RETURNING id, user_id, expires_at
            """),
            {"id": reset_id, "u": user_id, "h": token_hash, "by": created_by, "ttl": ttl},
        )
    ).one()
    return ResetRow(**row._mapping)


async def valid_password_reset(conn: AsyncConnection, token_hash: bytes) -> ResetRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT r.id, r.user_id, r.expires_at FROM password_resets r
                JOIN users u ON u.id = r.user_id AND u.disabled_at IS NULL
                WHERE r.token_hash = :h AND r.used_at IS NULL AND r.revoked_at IS NULL
                  AND r.expires_at > now()
            """),
            {"h": token_hash},
        )
    ).first()
    return ResetRow(**row._mapping) if row else None


async def consume_password_reset(conn: AsyncConnection, reset_id: uuid.UUID) -> bool:
    result = await conn.execute(
        text(
            "UPDATE password_resets SET used_at = now() WHERE id = :id "
            "AND used_at IS NULL AND revoked_at IS NULL AND expires_at > now()"
        ),
        {"id": reset_id},
    )
    return result.rowcount == 1

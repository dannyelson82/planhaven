"""Queries for users, sessions and setup tokens. Callers choose the transaction identity;
credential lookups happen in system context (nobody is identified yet)."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class UserRow:
    id: uuid.UUID
    email: str
    display_name: str
    password_hash: str
    is_admin: bool
    disabled: bool


@dataclass(frozen=True, slots=True)
class SessionRow:
    id: uuid.UUID
    user_id: uuid.UUID
    mfa_verified: bool
    reauth_at: datetime | None
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


async def any_admin(conn: AsyncConnection) -> bool:
    return bool(await conn.scalar(text("SELECT EXISTS (SELECT 1 FROM users WHERE is_admin)")))


async def user_by_email(conn: AsyncConnection, email: str) -> UserRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, email, display_name, password_hash, is_admin,
                       disabled_at IS NOT NULL AS disabled
                FROM users WHERE email = :e
            """),
            {"e": email},
        )
    ).first()
    return UserRow(**row._mapping) if row else None


async def user_by_id(conn: AsyncConnection, user_id: uuid.UUID) -> UserRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, email, display_name, password_hash, is_admin,
                       disabled_at IS NOT NULL AS disabled
                FROM users WHERE id = :id
            """),
            {"id": user_id},
        )
    ).first()
    return UserRow(**row._mapping) if row else None


async def create_user(
    conn: AsyncConnection, *, email: str, display_name: str, password_hash: str, is_admin: bool
) -> uuid.UUID:
    user_id = uuid.uuid7()
    await conn.execute(
        text(
            "INSERT INTO users (id, email, display_name, password_hash, is_admin) "
            "VALUES (:id, :email, :name, :hash, :admin)"
        ),
        {
            "id": user_id,
            "email": email,
            "name": display_name,
            "hash": password_hash,
            "admin": is_admin,
        },
    )
    return user_id


async def set_password_hash(conn: AsyncConnection, user_id: uuid.UUID, password_hash: str) -> None:
    await conn.execute(
        text(
            "UPDATE users SET password_hash = :h, updated_at = now(), version = version + 1 "
            "WHERE id = :id"
        ),
        {"h": password_hash, "id": user_id},
    )


# ---------------------------------------------------------------- sessions


async def create_session(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    token_hash: bytes,
    idle: timedelta,
    absolute: timedelta,
    ip: str | None,
    user_agent: str | None,
    mfa_verified: bool = False,
) -> uuid.UUID:
    session_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO sessions (id, token_hash, user_id, idle_expires_at,
                                  absolute_expires_at, ip, user_agent, mfa_verified, reauth_at)
            VALUES (:id, :th, :uid, now() + :idle, now() + :abs,
                    CAST(:ip AS inet), :ua, :mfa, CASE WHEN :mfa THEN now() END)
        """),
        {
            "id": session_id,
            "th": token_hash,
            "uid": user_id,
            "idle": idle,
            "abs": absolute,
            "ip": ip,
            "ua": (user_agent or "")[:200] or None,
            "mfa": mfa_verified,
        },
    )
    return session_id


async def active_session(conn: AsyncConnection, token_hash: bytes) -> SessionRow | None:
    """A session that isn't revoked or expired, belonging to an enabled user."""
    row = (
        await conn.execute(
            text("""
                SELECT s.id, s.user_id, s.mfa_verified, s.reauth_at, s.last_seen_at,
                       s.idle_expires_at, s.absolute_expires_at
                FROM sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = :th AND s.revoked_at IS NULL
                  AND s.idle_expires_at > now() AND s.absolute_expires_at > now()
                  AND u.disabled_at IS NULL
            """),
            {"th": token_hash},
        )
    ).first()
    return SessionRow(**row._mapping) if row else None


@dataclass(frozen=True, slots=True)
class OwnSessionRow:
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    ip: str | None
    user_agent: str | None


async def own_active_sessions(conn: AsyncConnection, user_id: uuid.UUID) -> list[OwnSessionRow]:
    rows = await conn.execute(
        text("""
            SELECT id, created_at, last_seen_at, host(ip) AS ip, user_agent FROM sessions
            WHERE user_id = :u AND revoked_at IS NULL
              AND idle_expires_at > now() AND absolute_expires_at > now()
            ORDER BY last_seen_at DESC LIMIT 100
        """),
        {"u": user_id},
    )
    return [OwnSessionRow(**r._mapping) for r in rows]


async def revoke_own_session(
    conn: AsyncConnection, user_id: uuid.UUID, session_id: uuid.UUID
) -> bool:
    result = await conn.execute(
        text(
            "UPDATE sessions SET revoked_at = now() "
            "WHERE id = :id AND user_id = :u AND revoked_at IS NULL"
        ),
        {"id": session_id, "u": user_id},
    )
    return result.rowcount == 1


async def touch_session(conn: AsyncConnection, session_id: uuid.UUID, idle: timedelta) -> None:
    await conn.execute(
        text(
            "UPDATE sessions SET last_seen_at = now(), "
            "idle_expires_at = least(now() + :idle, absolute_expires_at) WHERE id = :id"
        ),
        {"id": session_id, "idle": idle},
    )


async def revoke_session(conn: AsyncConnection, session_id: uuid.UUID) -> None:
    await conn.execute(
        text("UPDATE sessions SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL"),
        {"id": session_id},
    )


async def revoke_other_sessions(
    conn: AsyncConnection, user_id: uuid.UUID, keep: uuid.UUID | None
) -> int:
    result = await conn.execute(
        text(
            "UPDATE sessions SET revoked_at = now() WHERE user_id = :uid "
            "AND revoked_at IS NULL AND (CAST(:keep AS uuid) IS NULL OR id <> :keep)"
        ),
        {"uid": user_id, "keep": keep},
    )
    return result.rowcount


# ---------------------------------------------------------------- setup tokens


async def replace_setup_token(conn: AsyncConnection, token_hash: bytes, ttl: timedelta) -> None:
    """Only one setup token is ever valid: earlier unused ones are removed."""
    await conn.execute(text("DELETE FROM setup_tokens WHERE used_at IS NULL"))
    await conn.execute(
        text("INSERT INTO setup_tokens (token_hash, expires_at) VALUES (:h, now() + :ttl)"),
        {"h": token_hash, "ttl": ttl},
    )


async def consume_setup_token(conn: AsyncConnection, token_hash: bytes) -> bool:
    """Mark the token used if it's valid. Row-locked, so it can be used only once."""
    result = await conn.execute(
        text(
            "UPDATE setup_tokens SET used_at = now() WHERE token_hash = :h "
            "AND used_at IS NULL AND expires_at > now()"
        ),
        {"h": token_hash},
    )
    return result.rowcount == 1


async def record_audit(
    conn: AsyncConnection,
    *,
    action: str,
    actor_user_id: uuid.UUID | None,
    ip: str | None,
    actor_client: str = "web",
    details: str = "{}",
    project_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO audit_events (actor_user_id, actor_client, action, ip, details, "
            "project_id, resource_type, resource_id) "
            "VALUES (:actor, :client, :action, CAST(:ip AS inet), CAST(:details AS jsonb), "
            ":project, :rtype, :rid)"
        ),
        {
            "actor": actor_user_id,
            "client": actor_client,
            "action": action,
            "ip": ip,
            "details": details,
            "project": project_id,
            "rtype": resource_type,
            "rid": resource_id,
        },
    )

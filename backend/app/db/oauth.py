"""Queries for the OAuth authorization server and AI connections (ADR 0007, ADR 0019).

Clients, requests, codes and tokens are system-only (no session behind those requests).
Grants, suggestions and AI changes are each person's own (RLS)."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# ---------------------------------------------------------------- clients (system context)


@dataclass(frozen=True, slots=True)
class ClientRow:
    id: uuid.UUID
    client_id: str
    client_name: str
    redirect_uris: list[str]
    created_at: datetime


async def create_client(
    conn: AsyncConnection, client_id: str, client_name: str, redirect_uris: list[str]
) -> ClientRow:
    row = (
        await conn.execute(
            text("""
                INSERT INTO oauth_clients (client_id, client_name, redirect_uris)
                VALUES (:c, :n, CAST(:r AS text[]))
                RETURNING id, client_id, client_name, redirect_uris, created_at
            """),
            {"c": client_id, "n": client_name, "r": redirect_uris},
        )
    ).one()
    return ClientRow(**row._mapping)


async def client(conn: AsyncConnection, client_id: str) -> ClientRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, client_id, client_name, redirect_uris, created_at
                FROM oauth_clients WHERE client_id = :c
            """),
            {"c": client_id},
        )
    ).first()
    return ClientRow(**row._mapping) if row else None


async def client_by_id(conn: AsyncConnection, id_: uuid.UUID) -> ClientRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, client_id, client_name, redirect_uris, created_at
                FROM oauth_clients WHERE id = :i
            """),
            {"i": id_},
        )
    ).first()
    return ClientRow(**row._mapping) if row else None


# ---------------------------------------------------------------- authorization requests


@dataclass(frozen=True, slots=True)
class RequestRow:
    id: uuid.UUID
    client_id: uuid.UUID
    redirect_uri: str
    code_challenge: str
    scope: str
    state: str | None
    expires_at: datetime


async def create_request(
    conn: AsyncConnection,
    *,
    client_id: uuid.UUID,
    redirect_uri: str,
    code_challenge: str,
    scope: str,
    state: str | None,
) -> uuid.UUID:
    await conn.execute(text("DELETE FROM oauth_requests WHERE expires_at < now()"))
    value = await conn.scalar(
        text("""
            INSERT INTO oauth_requests (client_id, redirect_uri, code_challenge, scope, state,
                                        expires_at)
            VALUES (:c, :r, :ch, :s, :st, now() + interval '15 minutes') RETURNING id
        """),
        {"c": client_id, "r": redirect_uri, "ch": code_challenge, "s": scope, "st": state},
    )
    if not isinstance(value, uuid.UUID):
        raise RuntimeError("request not created")
    return value


async def request(conn: AsyncConnection, request_id: uuid.UUID) -> RequestRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, client_id, redirect_uri, code_challenge, scope, state, expires_at
                FROM oauth_requests WHERE id = :i AND expires_at > now()
            """),
            {"i": request_id},
        )
    ).first()
    return RequestRow(**row._mapping) if row else None


async def delete_request(conn: AsyncConnection, request_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM oauth_requests WHERE id = :i"), {"i": request_id})


# ---------------------------------------------------------------- grants (a person's connections)


@dataclass(frozen=True, slots=True)
class GrantRow:
    id: uuid.UUID
    user_id: uuid.UUID
    client_id: uuid.UUID
    client_name: str
    scope: str
    write_mode: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


async def create_grant(
    conn: AsyncConnection, *, user_id: uuid.UUID, client_id: uuid.UUID, scope: str, write_mode: str
) -> uuid.UUID:
    """One live connection per person and app: connecting again replaces the old one."""
    await conn.execute(
        text("""
            UPDATE oauth_grants SET revoked_at = now()
            WHERE user_id = :u AND client_id = :c AND revoked_at IS NULL
        """),
        {"u": user_id, "c": client_id},
    )
    value = await conn.scalar(
        text("""
            INSERT INTO oauth_grants (user_id, client_id, scope, write_mode)
            VALUES (:u, :c, :s, :m) RETURNING id
        """),
        {"u": user_id, "c": client_id, "s": scope, "m": write_mode},
    )
    if not isinstance(value, uuid.UUID):
        raise RuntimeError("grant not created")
    return value


async def grants_of(conn: AsyncConnection, user_id: uuid.UUID) -> list[GrantRow]:
    rows = await conn.execute(
        text(
            """
            SELECT g.id, g.user_id, g.client_id, c.client_name, g.scope, g.write_mode,
                   g.created_at, g.last_used_at, g.revoked_at
            FROM oauth_grants g JOIN oauth_clients c ON c.id = g.client_id
            WHERE g.user_id = :u AND g.revoked_at IS NULL ORDER BY g.created_at
            """
        ),
        {"u": user_id},
    )
    return [GrantRow(**r._mapping) for r in rows]


async def grant(conn: AsyncConnection, grant_id: uuid.UUID) -> GrantRow | None:
    row = (
        await conn.execute(
            text(
                """
                SELECT g.id, g.user_id, g.client_id, c.client_name, g.scope, g.write_mode,
                       g.created_at, g.last_used_at, g.revoked_at
                FROM oauth_grants g JOIN oauth_clients c ON c.id = g.client_id
                WHERE g.id = :i
                """
            ),
            {"i": grant_id},
        )
    ).first()
    return GrantRow(**row._mapping) if row else None


async def update_grant(
    conn: AsyncConnection, grant_id: uuid.UUID, *, scope: str, write_mode: str
) -> bool:
    result = await conn.execute(
        text("""
            UPDATE oauth_grants SET scope = :s, write_mode = :m
            WHERE id = :i AND revoked_at IS NULL
        """),
        {"i": grant_id, "s": scope, "m": write_mode},
    )
    return result.rowcount == 1


async def revoke_grant(conn: AsyncConnection, grant_id: uuid.UUID) -> bool:
    result = await conn.execute(
        text("UPDATE oauth_grants SET revoked_at = now() WHERE id = :i AND revoked_at IS NULL"),
        {"i": grant_id},
    )
    return result.rowcount == 1


async def grant_used(conn: AsyncConnection, grant_id: uuid.UUID) -> None:
    await conn.execute(
        text("""
            UPDATE oauth_grants SET last_used_at = now()
            WHERE id = :i AND (last_used_at IS NULL OR last_used_at < now() - interval '1 minute')
        """),
        {"i": grant_id},
    )


# ---------------------------------------------------------------- codes and tokens (system)


async def create_code(
    conn: AsyncConnection,
    *,
    code_hash: bytes,
    grant_id: uuid.UUID,
    redirect_uri: str,
    code_challenge: str,
) -> None:
    await conn.execute(
        text("""
            INSERT INTO oauth_codes (code_hash, grant_id, redirect_uri, code_challenge, expires_at)
            VALUES (:h, :g, :r, :c, now() + interval '2 minutes')
        """),
        {"h": code_hash, "g": grant_id, "r": redirect_uri, "c": code_challenge},
    )


@dataclass(frozen=True, slots=True)
class CodeRow:
    grant_id: uuid.UUID
    redirect_uri: str
    code_challenge: str
    expired: bool
    used: bool


async def take_code(conn: AsyncConnection, code_hash: bytes) -> CodeRow | None:
    """Look a code up and mark it used, in one step (a code works once)."""
    row = (
        await conn.execute(
            text("""
                UPDATE oauth_codes SET used_at = coalesce(used_at, now())
                WHERE code_hash = :h
                RETURNING grant_id, redirect_uri, code_challenge, expires_at < now() AS expired,
                          used_at < now() AS used
            """),
            {"h": code_hash},
        )
    ).first()
    return CodeRow(**row._mapping) if row else None


async def add_token(
    conn: AsyncConnection,
    *,
    grant_id: uuid.UUID,
    family_id: uuid.UUID,
    kind: str,
    token_hash: bytes,
    lifetime_seconds: int,
) -> None:
    await conn.execute(
        text("""
            INSERT INTO oauth_tokens (grant_id, family_id, kind, token_hash, expires_at)
            VALUES (:g, :f, :k, :h, now() + make_interval(secs => :s))
        """),
        {"g": grant_id, "f": family_id, "k": kind, "h": token_hash, "s": lifetime_seconds},
    )


@dataclass(frozen=True, slots=True)
class TokenRow:
    id: uuid.UUID
    grant_id: uuid.UUID
    family_id: uuid.UUID
    kind: str
    expired: bool
    used: bool
    revoked: bool


async def token(conn: AsyncConnection, token_hash: bytes) -> TokenRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT t.id, t.grant_id, t.family_id, t.kind, t.expires_at <= now() AS expired,
                       t.used_at IS NOT NULL AS used,
                       (t.revoked_at IS NOT NULL OR g.revoked_at IS NOT NULL
                        OR u.disabled_at IS NOT NULL) AS revoked
                FROM oauth_tokens t JOIN oauth_grants g ON g.id = t.grant_id
                JOIN users u ON u.id = g.user_id
                WHERE t.token_hash = :h
            """),
            {"h": token_hash},
        )
    ).first()
    return TokenRow(**row._mapping) if row else None


async def use_refresh(conn: AsyncConnection, token_id: uuid.UUID) -> bool:
    """Mark a refresh token used; False if it already was (a replay)."""
    result = await conn.execute(
        text("UPDATE oauth_tokens SET used_at = now() WHERE id = :i AND used_at IS NULL"),
        {"i": token_id},
    )
    return result.rowcount == 1


async def revoke_family(conn: AsyncConnection, family_id: uuid.UUID) -> None:
    await conn.execute(
        text("""
            UPDATE oauth_tokens SET revoked_at = now()
            WHERE family_id = :f AND revoked_at IS NULL
        """),
        {"f": family_id},
    )


async def revoke_grant_tokens(conn: AsyncConnection, grant_id: uuid.UUID) -> None:
    await conn.execute(
        text("""
            UPDATE oauth_tokens SET revoked_at = now()
            WHERE grant_id = :g AND revoked_at IS NULL
        """),
        {"g": grant_id},
    )


async def purge(conn: AsyncConnection) -> None:
    """Housekeeping: old codes, requests and expired tokens (system context)."""
    await conn.execute(text("DELETE FROM oauth_codes WHERE expires_at < now() - interval '1 day'"))
    await conn.execute(text("DELETE FROM oauth_requests WHERE expires_at < now()"))
    await conn.execute(
        text("DELETE FROM oauth_tokens WHERE expires_at < now() - interval '7 days'")
    )


# ---------------------------------------------------------------- suggestions and AI changes


@dataclass(frozen=True, slots=True)
class SuggestionRow:
    id: uuid.UUID
    grant_id: uuid.UUID
    client_name: str
    project_id: uuid.UUID | None
    tool: str
    arguments: dict[str, Any]
    summary: str
    status: str
    created_at: datetime


async def add_suggestion(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    grant_id: uuid.UUID,
    project_id: uuid.UUID | None,
    tool: str,
    arguments: dict[str, Any],
    summary: str,
) -> uuid.UUID:
    value = await conn.scalar(
        text("""
            INSERT INTO ai_suggestions (user_id, grant_id, project_id, tool, arguments, summary)
            VALUES (:u, :g, :p, :t, CAST(:a AS jsonb), :s) RETURNING id
        """),
        {
            "u": user_id,
            "g": grant_id,
            "p": project_id,
            "t": tool,
            "a": json.dumps(arguments),
            "s": summary,
        },
    )
    if not isinstance(value, uuid.UUID):
        raise RuntimeError("suggestion not saved")
    return value


async def suggestions(
    conn: AsyncConnection, user_id: uuid.UUID, *, pending_only: bool = True
) -> list[SuggestionRow]:
    rows = await conn.execute(
        text("""
            SELECT s.id, s.grant_id, c.client_name, s.project_id, s.tool, s.arguments, s.summary,
                   s.status, s.created_at
            FROM ai_suggestions s
            JOIN oauth_grants g ON g.id = s.grant_id
            JOIN oauth_clients c ON c.id = g.client_id
            WHERE s.user_id = :u AND (NOT :p OR s.status = 'pending')
            ORDER BY s.created_at LIMIT 200
        """),
        {"u": user_id, "p": pending_only},
    )
    return [SuggestionRow(**r._mapping) for r in rows]


async def decide(conn: AsyncConnection, suggestion_id: uuid.UUID, status: str) -> bool:
    result = await conn.execute(
        text("""
            UPDATE ai_suggestions SET status = :s, decided_at = now()
            WHERE id = :i AND status = 'pending'
        """),
        {"i": suggestion_id, "s": status},
    )
    return result.rowcount == 1


@dataclass(frozen=True, slots=True)
class ChangeRow:
    id: uuid.UUID
    client_name: str
    project_id: uuid.UUID | None
    kind: str
    summary: str
    undo: dict[str, Any]
    created_at: datetime
    undone_at: datetime | None


async def add_change(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    client_name: str,
    project_id: uuid.UUID | None,
    kind: str,
    summary: str,
    undo: dict[str, Any],
) -> uuid.UUID:
    value = await conn.scalar(
        text("""
            INSERT INTO ai_changes (user_id, client_name, project_id, kind, summary, undo)
            VALUES (:u, :c, :p, :k, :s, CAST(:d AS jsonb)) RETURNING id
        """),
        {
            "u": user_id,
            "c": client_name,
            "p": project_id,
            "k": kind,
            "s": summary,
            "d": json.dumps(undo),
        },
    )
    if not isinstance(value, uuid.UUID):
        raise RuntimeError("change not recorded")
    return value


async def changes(conn: AsyncConnection, user_id: uuid.UUID, limit: int = 100) -> list[ChangeRow]:
    rows = await conn.execute(
        text("""
            SELECT id, client_name, project_id, kind, summary, undo, created_at, undone_at
            FROM ai_changes WHERE user_id = :u ORDER BY created_at DESC LIMIT :n
        """),
        {"u": user_id, "n": limit},
    )
    return [ChangeRow(**r._mapping) for r in rows]


async def mark_undone(conn: AsyncConnection, change_id: uuid.UUID) -> bool:
    result = await conn.execute(
        text("UPDATE ai_changes SET undone_at = now() WHERE id = :i AND undone_at IS NULL"),
        {"i": change_id},
    )
    return result.rowcount == 1

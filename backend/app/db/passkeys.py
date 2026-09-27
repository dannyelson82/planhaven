"""Queries for passkeys and WebAuthn challenges."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class PasskeyRow:
    id: uuid.UUID
    user_id: uuid.UUID
    credential_id: bytes
    public_key: bytes
    sign_count: int
    transports: list[str]
    name: str
    created_at: datetime
    last_used_at: datetime | None


def _row(r: object) -> PasskeyRow:
    m = r._mapping  # type: ignore[attr-defined]
    return PasskeyRow(
        id=m["id"],
        user_id=m["user_id"],
        credential_id=bytes(m["credential_id"]),
        public_key=bytes(m["public_key"]),
        sign_count=m["sign_count"],
        transports=list(m["transports"]),
        name=m["name"],
        created_at=m["created_at"],
        last_used_at=m["last_used_at"],
    )


_COLUMNS = text("""
    SELECT id, user_id, credential_id, public_key, sign_count, transports, name, created_at,
           last_used_at
    FROM webauthn_credentials
""")


async def for_user(conn: AsyncConnection, user_id: uuid.UUID) -> list[PasskeyRow]:
    rows = await conn.execute(
        text(_COLUMNS.text + " WHERE user_id = :u ORDER BY created_at"), {"u": user_id}
    )
    return [_row(r) for r in rows]


async def by_credential_id(conn: AsyncConnection, credential_id: bytes) -> PasskeyRow | None:
    row = (
        await conn.execute(text(_COLUMNS.text + " WHERE credential_id = :c"), {"c": credential_id})
    ).first()
    return _row(row) if row else None


async def add(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    credential_id: bytes,
    public_key: bytes,
    sign_count: int,
    transports: list[str],
    name: str,
) -> uuid.UUID:
    passkey_id = uuid.uuid7()
    await conn.execute(
        text(
            "INSERT INTO webauthn_credentials (id, user_id, credential_id, public_key, "
            "sign_count, transports, name) VALUES (:id, :u, :c, :pk, :sc, :t, :n)"
        ),
        {
            "id": passkey_id,
            "u": user_id,
            "c": credential_id,
            "pk": public_key,
            "sc": sign_count,
            "t": transports,
            "n": name,
        },
    )
    return passkey_id


async def record_use(conn: AsyncConnection, passkey_id: uuid.UUID, sign_count: int) -> None:
    await conn.execute(
        text(
            "UPDATE webauthn_credentials SET sign_count = :sc, last_used_at = now() WHERE id = :id"
        ),
        {"id": passkey_id, "sc": sign_count},
    )


async def delete(conn: AsyncConnection, user_id: uuid.UUID, passkey_id: uuid.UUID) -> bool:
    result = await conn.execute(
        text("DELETE FROM webauthn_credentials WHERE id = :id AND user_id = :u"),
        {"id": passkey_id, "u": user_id},
    )
    return result.rowcount == 1


async def count_for_user(conn: AsyncConnection, user_id: uuid.UUID) -> int:
    n = await conn.scalar(
        text("SELECT count(*) FROM webauthn_credentials WHERE user_id = :u"), {"u": user_id}
    )
    return int(n or 0)


# ---------------------------------------------------------------- challenges


async def new_challenge(
    conn: AsyncConnection,
    *,
    challenge: bytes,
    purpose: str,
    user_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    ttl: timedelta,
) -> uuid.UUID:
    challenge_id = uuid.uuid7()
    await conn.execute(
        text("DELETE FROM webauthn_challenges WHERE expires_at < now() - interval '1 hour'")
    )
    await conn.execute(
        text(
            "INSERT INTO webauthn_challenges (id, challenge, purpose, user_id, session_id, "
            "expires_at) VALUES (:id, :c, :p, :u, :s, now() + :ttl)"
        ),
        {
            "id": challenge_id,
            "c": challenge,
            "p": purpose,
            "u": user_id,
            "s": session_id,
            "ttl": ttl,
        },
    )
    return challenge_id


async def take_challenge(
    conn: AsyncConnection,
    challenge_id: uuid.UUID,
    *,
    purpose: str,
    session_id: uuid.UUID | None,
) -> bytes | None:
    """Consume a challenge: valid once, unexpired, for this purpose and session."""
    value = await conn.scalar(
        text("""
            UPDATE webauthn_challenges SET used_at = now()
            WHERE id = :id AND purpose = :p AND used_at IS NULL AND expires_at > now()
              AND session_id IS NOT DISTINCT FROM :s
            RETURNING challenge
        """),
        {"id": challenge_id, "p": purpose, "s": session_id},
    )
    return bytes(value) if value is not None else None

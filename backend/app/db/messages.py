"""Queries for conversations and messages (user transactions; RLS: current members only).
People's names and online status come from system-context queries in the service, for the
ids these queries returned."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def start(conn: AsyncConnection, title: str | None, others: list[uuid.UUID]) -> uuid.UUID:
    value = await conn.scalar(
        text("SELECT app.start_conversation(:t, CAST(:o AS uuid[]))"), {"t": title, "o": others}
    )
    if not isinstance(value, uuid.UUID):
        raise RuntimeError("conversation not started")
    return value


@dataclass(frozen=True, slots=True)
class ConversationRow:
    id: uuid.UUID
    title: str | None
    is_direct: bool
    last_message_at: datetime | None
    last_read_at: datetime
    unread: int
    last_body: str | None
    last_sender: uuid.UUID | None
    last_deleted: bool | None


async def conversations(
    conn: AsyncConnection, me: uuid.UUID, only: uuid.UUID | None = None
) -> list[ConversationRow]:
    """This person's conversations (or just `only`), most recent first."""
    rows = await conn.execute(
        text("""
            SELECT c.id, c.title, c.direct_key IS NOT NULL AS is_direct, c.last_message_at,
                   me.last_read_at,
                   (SELECT count(*) FROM (
                        SELECT 1 FROM messages m
                        WHERE m.conversation_id = c.id AND m.created_at > me.last_read_at
                          AND m.sender_id <> me.user_id AND m.deleted_at IS NULL LIMIT 100) u
                   ) AS unread,
                   last.body AS last_body, last.sender_id AS last_sender,
                   last.deleted_at IS NOT NULL AS last_deleted
            FROM conversations c
            JOIN conversation_members me ON me.conversation_id = c.id AND me.user_id = :me
                                         AND me.left_at IS NULL
            LEFT JOIN LATERAL (
                SELECT body, sender_id, deleted_at FROM messages m
                WHERE m.conversation_id = c.id ORDER BY m.created_at DESC LIMIT 1
            ) last ON true
            WHERE CAST(:only AS uuid) IS NULL OR c.id = :only
            ORDER BY coalesce(c.last_message_at, c.created_at) DESC LIMIT 200
        """),
        {"me": me, "only": only},
    )
    return [ConversationRow(**r._mapping) for r in rows]


@dataclass(frozen=True, slots=True)
class MemberRow:
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    last_read_at: datetime
    left_at: datetime | None


async def members(conn: AsyncConnection, conversation_ids: list[uuid.UUID]) -> list[MemberRow]:
    rows = await conn.execute(
        text("""
            SELECT conversation_id, user_id, last_read_at, left_at FROM conversation_members
            WHERE conversation_id = ANY(:c) ORDER BY joined_at
        """),
        {"c": conversation_ids},
    )
    return [MemberRow(**r._mapping) for r in rows]


@dataclass(frozen=True, slots=True)
class MessageRow:
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    body: str
    created_at: datetime
    deleted: bool


async def messages(
    conn: AsyncConnection, conversation_id: uuid.UUID, before: datetime | None, limit: int
) -> list[MessageRow]:
    """Newest first; `before` pages back through older ones."""
    rows = await conn.execute(
        text("""
            SELECT id, conversation_id, sender_id, body, created_at,
                   deleted_at IS NOT NULL AS deleted
            FROM messages
            WHERE conversation_id = :c
              AND (CAST(:before AS timestamptz) IS NULL OR created_at < :before)
            ORDER BY created_at DESC LIMIT :n
        """),
        {"c": conversation_id, "before": before, "n": limit},
    )
    return [MessageRow(**r._mapping) for r in rows]


async def get_message(conn: AsyncConnection, message_id: uuid.UUID) -> MessageRow | None:
    row = (
        await conn.execute(
            text("""
                SELECT id, conversation_id, sender_id, body, created_at,
                       deleted_at IS NOT NULL AS deleted
                FROM messages WHERE id = :id
            """),
            {"id": message_id},
        )
    ).first()
    return MessageRow(**row._mapping) if row else None


async def add_message(
    conn: AsyncConnection, conversation_id: uuid.UUID, sender: uuid.UUID, body: str
) -> uuid.UUID:
    message_id = uuid.uuid7()
    await conn.execute(
        text("""
            INSERT INTO messages (id, conversation_id, sender_id, body)
            VALUES (:id, :c, :s, :b)
        """),
        {"id": message_id, "c": conversation_id, "s": sender, "b": body},
    )
    await conn.execute(
        text("UPDATE conversations SET last_message_at = now() WHERE id = :c"),
        {"c": conversation_id},
    )
    await mark_read(conn, conversation_id, sender)
    return message_id


async def delete_message(conn: AsyncConnection, message_id: uuid.UUID) -> bool:
    """The text is removed, not hidden."""
    result = await conn.execute(
        text("""
            UPDATE messages SET body = '', deleted_at = now()
            WHERE id = :id AND deleted_at IS NULL
        """),
        {"id": message_id},
    )
    return result.rowcount == 1


async def mark_read(conn: AsyncConnection, conversation_id: uuid.UUID, me: uuid.UUID) -> None:
    await conn.execute(
        text("""
            UPDATE conversation_members SET last_read_at = now()
            WHERE conversation_id = :c AND user_id = :me
        """),
        {"c": conversation_id, "me": me},
    )
    await conn.execute(
        text("""
            UPDATE notifications SET read_at = now()
            WHERE user_id = :me AND kind = 'message' AND read_at IS NULL
              AND data->>'conversation_id' = :cid
        """),
        {"cid": str(conversation_id), "me": me},
    )


async def leave(conn: AsyncConnection, conversation_id: uuid.UUID, me: uuid.UUID) -> None:
    await conn.execute(
        text("""
            UPDATE conversation_members SET left_at = now()
            WHERE conversation_id = :c AND user_id = :me AND left_at IS NULL
        """),
        {"c": conversation_id, "me": me},
    )


async def rename(conn: AsyncConnection, conversation_id: uuid.UUID, title: str) -> None:
    await conn.execute(
        text("UPDATE conversations SET title = :t WHERE id = :c AND direct_key IS NULL"),
        {"c": conversation_id, "t": title},
    )


async def add_member(conn: AsyncConnection, conversation_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Into a group: a new member, or someone who left coming back."""
    back = await conn.execute(
        text("""
            UPDATE conversation_members SET left_at = NULL
            WHERE conversation_id = :c AND user_id = :u AND left_at IS NOT NULL
        """),
        {"c": conversation_id, "u": user_id},
    )
    if back.rowcount == 0:
        await conn.execute(
            text("""
                INSERT INTO conversation_members (conversation_id, user_id) VALUES (:c, :u)
                ON CONFLICT (conversation_id, user_id) DO NOTHING
            """),
            {"c": conversation_id, "u": user_id},
        )


# ---------------------------------------------------------------- system context


@dataclass(frozen=True, slots=True)
class PersonRow:
    id: uuid.UUID
    display_name: str
    last_seen_at: datetime | None
    hide_presence: bool


async def people(conn: AsyncConnection) -> list[PersonRow]:
    """Everyone with an active account (system context)."""
    rows = await conn.execute(
        text("""
            SELECT u.id, u.display_name,
                   (SELECT max(s.last_seen_at) FROM sessions s WHERE s.user_id = u.id)
                     AS last_seen_at,
                   coalesce(p.hide_presence, false) AS hide_presence
            FROM users u LEFT JOIN people_settings p ON p.user_id = u.id
            WHERE u.disabled_at IS NULL ORDER BY lower(u.display_name) LIMIT 1000
        """)
    )
    return [PersonRow(**r._mapping) for r in rows]


async def names(conn: AsyncConnection, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = await conn.execute(
        text("SELECT id, display_name FROM users WHERE id = ANY(:u)"), {"u": user_ids}
    )
    return {r.id: r.display_name for r in rows}


async def active(conn: AsyncConnection, user_id: uuid.UUID) -> bool:
    found = await conn.scalar(
        text("SELECT 1 FROM users WHERE id = :u AND disabled_at IS NULL"), {"u": user_id}
    )
    return found is not None


async def forget_preview(conn: AsyncConnection, message_id: uuid.UUID) -> None:
    """A deleted message's text leaves the notifications that previewed it."""
    await conn.execute(
        text("""
            UPDATE notifications SET data = data - 'preview'
            WHERE kind = 'message' AND data->>'message_id' = :m
        """),
        {"m": str(message_id)},
    )


async def hide_presence(conn: AsyncConnection, user_id: uuid.UUID) -> bool:
    value = await conn.scalar(
        text("SELECT hide_presence FROM people_settings WHERE user_id = :u"), {"u": user_id}
    )
    return bool(value)


async def set_hide_presence(conn: AsyncConnection, user_id: uuid.UUID, hidden: bool) -> None:
    await conn.execute(
        text("""
            INSERT INTO people_settings (user_id, hide_presence) VALUES (:u, :h)
            ON CONFLICT (user_id) DO UPDATE SET hide_presence = EXCLUDED.hide_presence,
                                                updated_at = now()
        """),
        {"u": user_id, "h": hidden},
    )

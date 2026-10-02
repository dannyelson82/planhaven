"""Messages between people, and who's online (ADR 0018).

Anyone with an account can message anyone: one-to-one or a named group. Only a conversation's
current members see it (RLS); admins have no access. Messages are stored like notes (not
end-to-end encrypted). A sender can delete their own message: its text is removed, also from
the notifications that previewed it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app import authz
from app.db import auth as audit
from app.db import messages as store
from app.db import notifications as notification_store
from app.db.database import Database
from app.services import limits, live
from app.services.auth import CurrentSession

MAX_BODY = 4000
PAGE = 50
ONLINE_GRACE_MINUTES = 2  # shown "online" this long after the app was last open


class MessageError(ValueError):
    """A request that can't be done as asked (shown to the person)."""


@dataclass(frozen=True, slots=True)
class Person:
    id: uuid.UUID
    name: str
    online: bool
    last_seen: datetime | None  # to the minute; None when hidden or never


@dataclass(frozen=True, slots=True)
class Conversation:
    id: uuid.UUID
    title: str  # the group's name, or the other person's
    is_group: bool
    members: list[Person]
    unread: int
    last_message_at: datetime | None
    last_preview: str  # "" when none; "Message deleted" for a deleted one
    last_from_me: bool


@dataclass(frozen=True, slots=True)
class Message:
    id: uuid.UUID
    sender_id: uuid.UUID
    sender_name: str
    body: str
    created_at: datetime
    deleted: bool
    mine: bool


def _minute(value: datetime | None) -> datetime | None:
    return value.replace(second=0, microsecond=0) if value else None


async def _people(db: Database) -> dict[uuid.UUID, Person]:
    now_online = live.online()
    async with db.system_transaction() as conn:
        rows = await store.people(conn)
    return {
        r.id: Person(
            r.id,
            r.display_name,
            online=(r.id in now_online) and not r.hide_presence,
            last_seen=None if r.hide_presence else _minute(r.last_seen_at),
        )
        for r in rows
    }


async def people(db: Database, session: CurrentSession) -> list[Person]:
    """Everyone else on this PlanHaven, to start a conversation with."""
    authz.require(session.principal, authz.Action.USE_APP)
    return [p for p in (await _people(db)).values() if p.id != session.user.id]


async def get_hidden(db: Database, session: CurrentSession) -> bool:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        return await store.hide_presence(conn, session.user.id)


async def set_hidden(db: Database, session: CurrentSession, hidden: bool) -> None:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.user_transaction(session.user.id) as conn:
        await store.set_hide_presence(conn, session.user.id, hidden)


def _preview(row: store.ConversationRow) -> str:
    if row.last_deleted:
        return "Message deleted"
    return (row.last_body or "")[:120]


async def conversations(
    db: Database, session: CurrentSession, only: uuid.UUID | None = None
) -> list[Conversation]:
    authz.require(session.principal, authz.Action.USE_APP)
    me = session.user.id
    async with db.user_transaction(me) as conn:
        rows = await store.conversations(conn, me, only)
        members = await store.members(conn, [r.id for r in rows])
    everyone = await _people(db)
    gone = [m.user_id for m in members if m.user_id not in everyone]
    if gone:  # disabled accounts still show by name
        async with db.system_transaction() as conn:
            for user_id, name in (await store.names(conn, gone)).items():
                everyone[user_id] = Person(user_id, name, False, None)
    out = []
    for r in rows:
        current = [
            everyone[m.user_id]
            for m in members
            if m.conversation_id == r.id and m.left_at is None and m.user_id in everyone
        ]
        others = [p for p in current if p.id != me]
        title = r.title or (others[0].name if others else "Just you")
        out.append(
            Conversation(
                r.id,
                title,
                not r.is_direct,
                current,
                r.unread,
                r.last_message_at,
                _preview(r),
                r.last_sender == me,
            )
        )
    return out


async def _get(db: Database, session: CurrentSession, conversation_id: uuid.UUID) -> Conversation:
    found = await conversations(db, session, conversation_id)
    if not found:
        raise authz.NotFoundError("Not found.")
    return found[0]


async def start(
    db: Database,
    session: CurrentSession,
    *,
    people_ids: list[uuid.UUID],
    title: str | None,
    ip: str | None,
) -> Conversation:
    """One person and no name: the one-to-one conversation (the existing one if there is).
    A name: a new group."""
    authz.require(session.principal, authz.Action.USE_APP)
    others = sorted({p for p in people_ids if p != session.user.id})
    if not others:
        raise MessageError("Choose who to message.")
    if title is None and len(others) != 1:
        raise MessageError("Give the group a name.")
    await limits.check(
        db,
        [(limits.CONVERSATION_START, limits.key(limits.CONVERSATION_START, session.user.id))],
        ip=ip,
        user_id=session.user.id,
    )
    async with db.system_transaction() as conn:
        for person in others:
            if not await store.active(conn, person):
                raise authz.NotFoundError("Not found.")
    async with db.user_transaction(session.user.id) as conn:
        conversation_id = await store.start(conn, title, others)
        await audit.record_audit(
            conn,
            action="conversation.started",
            actor_user_id=session.user.id,
            ip=ip,
            resource_type="conversation",
            resource_id=conversation_id,
        )
    return await _get(db, session, conversation_id)


async def messages(
    db: Database,
    session: CurrentSession,
    conversation_id: uuid.UUID,
    before: datetime | None,
) -> list[Message]:
    conversation = await _get(db, session, conversation_id)
    names = {p.id: p.name for p in conversation.members}
    async with db.user_transaction(session.user.id) as conn:
        rows = await store.messages(conn, conversation_id, before, PAGE)
    missing = [r.sender_id for r in rows if r.sender_id not in names]
    if missing:  # people who left the group
        async with db.system_transaction() as conn:
            names |= await store.names(conn, missing)
    return [
        Message(
            r.id,
            r.sender_id,
            names.get(r.sender_id, "Someone"),
            r.body,
            r.created_at,
            r.deleted,
            r.sender_id == session.user.id,
        )
        for r in rows
    ]


async def send(
    db: Database, session: CurrentSession, conversation_id: uuid.UUID, body: str, ip: str | None
) -> Message:
    body = body.strip()
    if not body:
        raise MessageError("Write something first.")
    if len(body) > MAX_BODY:
        raise MessageError("That message is too long.")
    await limits.check(
        db,
        [(limits.MESSAGE_SEND, limits.key(limits.MESSAGE_SEND, session.user.id))],
        ip=ip,
        user_id=session.user.id,
    )
    conversation = await _get(db, session, conversation_id)
    me = session.user.id
    async with db.user_transaction(me) as conn:
        message_id = await store.add_message(conn, conversation_id, me, body)
        members = await store.members(conn, [conversation_id])
    # Each other member hears about it once until they read the conversation (system context:
    # their notifications).
    async with db.system_transaction() as conn:
        for m in members:
            if m.user_id == me or m.left_at is not None:
                continue
            await notification_store.notify(
                conn,
                m.user_id,
                "message",
                {
                    "conversation_id": str(conversation_id),
                    "message_id": str(message_id),
                    "from": session.user.display_name[:80],
                    "group": conversation.title[:100] if conversation.is_group else "",
                    "preview": body[:100],
                },
                f"message:{conversation_id}:{m.last_read_at.astimezone(UTC).isoformat()}",
            )
    for m in members:
        if m.left_at is None:
            live.publish_to(m.user_id, "messages")
            if m.user_id != me:
                live.publish_to(m.user_id, "notifications")
    return Message(message_id, me, session.user.display_name, body, datetime.now(UTC), False, True)


async def delete(db: Database, session: CurrentSession, message_id: uuid.UUID) -> None:
    me = session.user.id
    async with db.user_transaction(me) as conn:
        message = await store.get_message(conn, message_id)
        if message is None:
            raise authz.NotFoundError("Not found.")
        if message.sender_id != me:
            raise authz.ForbiddenError("Only the sender can delete a message.")
        await store.delete_message(conn, message_id)
        members = await store.members(conn, [message.conversation_id])
    async with db.system_transaction() as conn:
        await store.forget_preview(conn, message_id)
    for m in members:
        if m.left_at is None:
            live.publish_to(m.user_id, "messages")


async def mark_read(db: Database, session: CurrentSession, conversation_id: uuid.UUID) -> None:
    await _get(db, session, conversation_id)
    async with db.user_transaction(session.user.id) as conn:
        await store.mark_read(conn, conversation_id, session.user.id)
    live.publish_to(session.user.id, "notifications")


async def leave(db: Database, session: CurrentSession, conversation_id: uuid.UUID) -> None:
    conversation = await _get(db, session, conversation_id)
    if not conversation.is_group:
        raise MessageError("You can leave groups, not one-to-one conversations.")
    async with db.user_transaction(session.user.id) as conn:
        await store.leave(conn, conversation_id, session.user.id)
    for p in conversation.members:
        live.publish_to(p.id, "messages")


async def rename(
    db: Database, session: CurrentSession, conversation_id: uuid.UUID, title: str
) -> None:
    conversation = await _get(db, session, conversation_id)
    if not conversation.is_group:
        raise MessageError("Only groups have a name.")
    async with db.user_transaction(session.user.id) as conn:
        await store.rename(conn, conversation_id, title)
    for p in conversation.members:
        live.publish_to(p.id, "messages")


async def add_member(
    db: Database, session: CurrentSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    conversation = await _get(db, session, conversation_id)
    if not conversation.is_group:
        raise MessageError("Start a group to talk with more people.")
    async with db.system_transaction() as conn:
        if not await store.active(conn, user_id):
            raise authz.NotFoundError("Not found.")
    async with db.user_transaction(session.user.id) as conn:
        await store.add_member(conn, conversation_id, user_id)
    for p in [*conversation.members, Person(user_id, "", False, None)]:
        live.publish_to(p.id, "messages")

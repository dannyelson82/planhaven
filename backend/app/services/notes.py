"""Notes: metadata over REST, and real-time co-editing rooms (ADR 0011, SECURITY.md §7.15).

A room holds one note's CRDT document in memory while anyone has it open. Every accepted edit
is persisted as an attributed update (in a transaction acting as the editor, so RLS applies)
and relayed to the other participants. Viewers receive edits; any edit they send closes their
connection. Edit contents are never logged.
"""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pycrdt

from app import authz
from app.db import auth as audit
from app.db import notes as store
from app.db import projects as project_store
from app.db.database import Database
from app.services import auth as auth_service
from app.services import live
from app.services.auth import CurrentSession
from app.services.projects import ConflictError

log = logging.getLogger("planhaven.collab")

NoteRow = store.NoteRow

MAX_MESSAGE_BYTES = 256 * 1024
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_AWARENESS_BYTES = 16 * 1024
# Browsers bundle edits (10/s) and cursor moves (4/s); this leaves room for several open
# tabs per person while still cutting off a flood.
MESSAGES_PER_WINDOW = 600
WINDOW_SECONDS = 10.0
RECHECK_SECONDS = 15.0
MAX_TEXT_CONTENT = 200_000
COMPACT_THRESHOLD = 200


class CollabCloseError(Exception):
    """Close the connection with a WebSocket close code (4xxx) and a short reason."""

    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


# ---------------------------------------------------------------- REST


async def _access(conn: Any, project_id: uuid.UUID) -> authz.ProjectAccess:
    access = authz.ProjectAccess(await project_store.role(conn, project_id))
    if access.role is not None and await project_store.get_project(conn, project_id) is None:
        return authz.ProjectAccess(None)
    return access


async def _note_access(conn: Any, note_id: uuid.UUID) -> tuple[NoteRow, authz.ProjectAccess]:
    note = await store.get_note(conn, note_id)
    if note is None:
        raise authz.NotFoundError("Not found.")
    return note, await _access(conn, note.project_id)


def _require(session: CurrentSession, access: authz.ProjectAccess, write: bool) -> None:
    authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
    if write:
        authz.require(session.principal, authz.Action.PROJECT_EDIT, access)


async def notes_for_project(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> list[NoteRow]:
    async with db.user_transaction(session.user.id) as conn:
        _require(session, await _access(conn, project_id), write=False)
        return await store.notes_for_project(conn, project_id)


async def create_note(
    db: Database, session: CurrentSession, project_id: uuid.UUID, title: str, ip: str | None
) -> NoteRow:
    async with db.user_transaction(session.user.id) as conn:
        _require(session, await _access(conn, project_id), write=True)
        note_id = await store.create_note(
            conn, project_id=project_id, user_id=session.user.id, title=title
        )
        await audit.record_audit(
            conn,
            action="note.created",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=project_id,
            resource_type="note",
            resource_id=note_id,
        )
        note = await store.get_note(conn, note_id)
    if note is None:
        raise RuntimeError("created note not visible")
    live.publish(project_id, "notes")
    return note


async def get_note(
    db: Database, session: CurrentSession, note_id: uuid.UUID
) -> tuple[NoteRow, bool]:
    """The note and whether the caller may edit it."""
    async with db.user_transaction(session.user.id) as conn:
        note, access = await _note_access(conn, note_id)
        _require(session, access, write=False)
    return note, authz.allowed(session.principal, authz.Action.PROJECT_EDIT, access)


async def rename(
    db: Database,
    session: CurrentSession,
    note_id: uuid.UUID,
    expected_version: int,
    title: str,
    ip: str | None,
) -> NoteRow:
    async with db.user_transaction(session.user.id) as conn:
        note, access = await _note_access(conn, note_id)
        _require(session, access, write=True)
        if await store.update_title(conn, note_id, expected_version, title) is None:
            raise ConflictError("This note was changed elsewhere. Reload and try again.")
        await audit.record_audit(
            conn,
            action="note.renamed",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=note.project_id,
            resource_type="note",
            resource_id=note_id,
        )
        after = await store.get_note(conn, note_id)
    if after is None:
        raise authz.NotFoundError("Not found.")
    live.publish(note.project_id, "notes")
    return after


async def set_text(
    db: Database, session: CurrentSession, note_id: uuid.UUID, text_content: str
) -> None:
    """Plain-text copy for search, AI and export, sent by the editor when it goes idle."""
    async with db.user_transaction(session.user.id) as conn:
        _note, access = await _note_access(conn, note_id)
        _require(session, access, write=True)
        await store.set_text(conn, note_id, text_content[:MAX_TEXT_CONTENT])


async def delete_note(
    db: Database, session: CurrentSession, note_id: uuid.UUID, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        note, access = await _note_access(conn, note_id)
        _require(session, access, write=True)
        await store.delete_note(conn, note_id)
        await audit.record_audit(
            conn,
            action="note.deleted",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=note.project_id,
            resource_type="note",
            resource_id=note_id,
        )
    live.publish(note.project_id, "notes")
    rooms.close_note(note_id, 4404, "note deleted")


# ---------------------------------------------------------------- collaboration


Send = Callable[[bytes], Awaitable[None]]


@dataclass(eq=False)
class Peer:
    send: Send
    user_id: uuid.UUID
    can_write: bool
    close: Callable[[int, str], Awaitable[None]]
    window_start: float = field(default_factory=time.monotonic)
    window_count: int = 0


@dataclass(eq=False)
class Room:
    note_id: uuid.UUID
    project_id: uuid.UUID
    doc: pycrdt.Doc[Any]
    size: int
    peers: set[Peer] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Rooms:
    def __init__(self) -> None:
        self._rooms: dict[uuid.UUID, Room] = {}
        self._loading = asyncio.Lock()
        self._closing: set[asyncio.Task[None]] = set()

    async def join(self, db: Database, user_id: uuid.UUID, note: NoteRow, peer: Peer) -> Room:
        async with self._loading:
            room = self._rooms.get(note.id)
            if room is None:
                async with db.user_transaction(user_id) as conn:
                    snapshot, updates = await store.load_state(conn, note.id)
                doc: pycrdt.Doc[Any] = pycrdt.Doc()
                size = 0
                for blob in ([snapshot] if snapshot else []) + updates:
                    doc.apply_update(blob)
                    size += len(blob)
                room = Room(note.id, note.project_id, doc, size)
                self._rooms[note.id] = room
            room.peers.add(peer)
            return room

    def leave(self, room: Room, peer: Peer) -> None:
        room.peers.discard(peer)
        if not room.peers:
            self._rooms.pop(room.note_id, None)

    def close_note(self, note_id: uuid.UUID, code: int, reason: str) -> None:
        room = self._rooms.get(note_id)
        if room:
            for peer in list(room.peers):
                task = asyncio.ensure_future(peer.close(code, reason))
                self._closing.add(task)
                task.add_done_callback(self._closing.discard)

    def membership_changed(
        self, project_id: uuid.UUID, user_id: uuid.UUID, role: str | None
    ) -> None:
        """Apply a sharing change to this person's open notes in the project at once:
        removed means disconnected; a new role changes whether their edits are accepted.
        (Connections also re-check every RECHECK_SECONDS.)"""
        for room, peer in self.peers_of(user_id):
            if room.project_id != project_id:
                continue
            if role is None:
                task = asyncio.ensure_future(peer.close(4403, "access removed"))
                self._closing.add(task)
                task.add_done_callback(self._closing.discard)
            else:
                peer.can_write = role in ("owner", "editor")

    def peers_of(self, user_id: uuid.UUID) -> list[tuple[Room, Peer]]:
        return [(r, p) for r in self._rooms.values() for p in r.peers if p.user_id == user_id]


rooms = Rooms()


def _rate_ok(peer: Peer) -> bool:
    now = time.monotonic()
    if now - peer.window_start > WINDOW_SECONDS:
        peer.window_start, peer.window_count = now, 0
    peer.window_count += 1
    return peer.window_count <= MESSAGES_PER_WINDOW


async def handle_message(db: Database, room: Room, peer: Peer, message: bytes) -> None:
    """Process one frame from a peer: sync (0) or awareness (1)."""
    if len(message) > MAX_MESSAGE_BYTES:
        raise CollabCloseError(4413, "message too large")
    if not _rate_ok(peer):
        raise CollabCloseError(4429, "too many messages")
    if not message:
        return
    kind = message[0]
    if kind == pycrdt.YMessageType.AWARENESS:
        if len(message) > MAX_AWARENESS_BYTES:
            raise CollabCloseError(4413, "awareness too large")
        await _broadcast(room, message, exclude=peer)
        return
    if kind != pycrdt.YMessageType.SYNC or len(message) < 2:
        raise CollabCloseError(4400, "unknown message")

    sync_type = message[1]
    if sync_type == pycrdt.YSyncMessageType.SYNC_STEP1:
        reply = pycrdt.handle_sync_message(message[1:], room.doc)
        if reply:
            await peer.send(reply)
        return
    if sync_type not in (pycrdt.YSyncMessageType.SYNC_STEP2, pycrdt.YSyncMessageType.SYNC_UPDATE):
        raise CollabCloseError(4400, "unknown sync message")
    try:
        update = pycrdt.read_message(message[2:])
    except Exception:
        raise CollabCloseError(4400, "malformed update") from None
    if update in (b"", b"\x00\x00"):
        return
    if not peer.can_write:
        raise CollabCloseError(4403, "read-only")
    if room.size + len(update) > MAX_DOCUMENT_BYTES:
        raise CollabCloseError(4413, "document too large")

    async with room.lock:
        before = room.doc.get_state()
        try:
            room.doc.apply_update(update)
        except Exception:
            raise CollabCloseError(4400, "malformed update") from None
        if room.doc.get_state() == before:
            return  # nothing new (already known)
        async with db.user_transaction(peer.user_id) as conn:
            await store.append_update(
                conn,
                note_id=room.note_id,
                project_id=room.project_id,
                user_id=peer.user_id,
                update=update,
            )
        room.size += len(update)
    await _broadcast(room, pycrdt.create_update_message(update), exclude=peer)
    log.info("note updated", extra={"note_id": str(room.note_id), "bytes": len(update)})


async def _broadcast(room: Room, message: bytes, exclude: Peer | None) -> None:
    for other in list(room.peers):
        if other is not exclude:
            try:
                await other.send(message)
            except Exception:
                room.peers.discard(other)


def opening_messages(room: Room) -> list[bytes]:
    """Sent on connect: the server's sync step 1 (the client replies with what it has)."""
    return [pycrdt.create_sync_message(room.doc)]


async def still_allowed(db: Database, token: str, note: NoteRow) -> tuple[bool, bool]:
    """Re-check on a timer: is the session still valid, and may this user still read/write?"""
    session = await auth_service.authenticate(db, token)
    if session is None or not session.mfa_verified:
        return False, False
    async with db.user_transaction(session.user.id) as conn:
        access = await _access(conn, note.project_id)
        if await store.get_note(conn, note.id) is None:
            return False, False
    readable = authz.allowed(session.principal, authz.Action.PROJECT_VIEW, access)
    writable = authz.allowed(session.principal, authz.Action.PROJECT_EDIT, access)
    return readable, writable


async def compact_notes(db: Database) -> int:
    """System job: fold many small updates into a snapshot."""
    done = 0
    async with db.system_transaction() as conn:
        note_ids = await store.notes_to_compact(conn, COMPACT_THRESHOLD)
    for note_id in note_ids:
        async with db.system_transaction() as conn:
            snapshot, updates = await store.load_state(conn, note_id)
            last = await store.last_update_id(conn, note_id)
            doc: pycrdt.Doc[Any] = pycrdt.Doc()
            for blob in ([snapshot] if snapshot else []) + updates:
                doc.apply_update(blob)
            await store.compact(conn, note_id, doc.get_update(), last)
        done += 1
    return done


# ---------------------------------------------------------------- checklists outside the editor
# The project page shows each note's checkboxes and can tick them without opening the note.
# The change is made to the note's CRDT document on the server, exactly like an edit from a
# browser: stored with attribution, sent live to anyone with the note open.

MAX_CHECKLIST_NOTES = 50
_TASK_MARKER = re.compile(r"^(\s*- \[)([ x])(\] )", re.MULTILINE)


class ChecklistChangedError(Exception):
    """The checklist changed since the page was loaded (message is safe to show)."""


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    index: int
    text: str
    checked: bool


def _task_items(node: Any) -> list[Any]:
    """Every checklist item in the document, in reading order (nested ones included)."""
    found: list[Any] = []
    for child in node.children:
        if isinstance(child, pycrdt.XmlElement):
            if child.tag == "taskItem":
                found.append(child)
            found.extend(_task_items(child))
    return found


def _item_text(item: Any) -> str:
    """The item's own words (formatting and nested lists left out)."""
    parts: list[str] = []

    def collect(node: Any) -> None:
        for child in node.children:
            if isinstance(child, pycrdt.XmlText):
                parts.extend(segment for segment, _ in child.diff())
            elif isinstance(child, pycrdt.XmlElement) and child.tag != "taskList":
                collect(child)

    collect(item)
    return "".join(parts).strip()


def checklist(doc: pycrdt.Doc[Any]) -> list[ChecklistItem]:
    fragment = doc.get("default", type=pycrdt.XmlFragment)
    return [
        ChecklistItem(i, _item_text(item)[:300], item.attributes.get("checked") is True)
        for i, item in enumerate(_task_items(fragment))
    ]


def _tick_in_text(text_content: str, index: int, checked: bool) -> str:
    """Keep the Markdown copy in step (task items appear there in the same order)."""
    count = -1

    def swap(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        if count != index:
            return match.group(0)
        return f"{match.group(1)}{'x' if checked else ' '}{match.group(3)}"

    return _TASK_MARKER.sub(swap, text_content)


async def _load_doc(db: Database, user_id: uuid.UUID, note_id: uuid.UUID) -> pycrdt.Doc[Any]:
    async with db.user_transaction(user_id) as conn:
        snapshot, updates = await store.load_state(conn, note_id)
    doc: pycrdt.Doc[Any] = pycrdt.Doc()
    for blob in ([snapshot] if snapshot else []) + updates:
        doc.apply_update(blob)
    return doc


async def project_checklists(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> list[tuple[NoteRow, list[ChecklistItem]]]:
    """Notes in the project that have checkboxes, with their items."""
    notes = await notes_for_project(db, session, project_id)
    result = []
    for note in notes[:MAX_CHECKLIST_NOTES]:
        room = rooms._rooms.get(note.id)
        doc = room.doc if room else await _load_doc(db, session.user.id, note.id)
        items = checklist(doc)
        if items:
            result.append((note, items))
    return result


async def set_checked(
    db: Database,
    session: CurrentSession,
    note_id: uuid.UUID,
    index: int,
    text: str,
    checked: bool,
) -> None:
    """Tick or untick one checkbox. `text` must match the item at `index`, so a stale page
    can't tick the wrong line."""
    async with db.user_transaction(session.user.id) as conn:
        note, access = await _note_access(conn, note_id)
        _require(session, access, write=True)

    async def change(doc: pycrdt.Doc[Any]) -> bytes | None:
        items = _task_items(doc.get("default", type=pycrdt.XmlFragment))
        if index >= len(items) or _item_text(items[index])[:300] != text:
            raise ChecklistChangedError("This checklist changed. Reload and try again.")
        if (items[index].attributes.get("checked") is True) == checked:
            return None
        before = doc.get_state()
        items[index].attributes["checked"] = checked
        return doc.get_update(before)

    async def persist(update: bytes) -> None:
        async with db.user_transaction(session.user.id) as conn:
            await store.append_update(
                conn,
                note_id=note.id,
                project_id=note.project_id,
                user_id=session.user.id,
                update=update,
            )
            current = await store.get_note(conn, note.id)
            if current is not None:
                await store.set_text(
                    conn, note.id, _tick_in_text(current.text_content, index, checked)
                )

    # Hold the loader (so nobody can open the note halfway) and, if it's open, its room.
    async with rooms._loading:
        room = rooms._rooms.get(note_id)
        if room is not None:
            async with room.lock:
                update = await change(room.doc)
                if update is not None:
                    await persist(update)
                    room.size += len(update)
        else:
            update = await change(await _load_doc(db, session.user.id, note_id))
            if update is not None:
                await persist(update)
    if update is None:
        return
    if room is not None:
        await _broadcast(room, pycrdt.create_update_message(update), exclude=None)
    log.info("note checklist ticked", extra={"note_id": str(note.id), "bytes": len(update)})
    live.publish(note.project_id, "notes")

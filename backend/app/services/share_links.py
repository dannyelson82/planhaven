"""Share links for people without an account (ADR 0015; owner decisions 2026-09-28).

Project owners and editors make a link (with a fresh second factor), ticking exactly what
whoever holds it may see and do. The guest opens it, gives their name (and the PIN, if the link
has one), and gets a short-lived session limited to that link. Every guest action is checked
twice: here (authz.require_link) and by the database, item by item (link transactions,
migration 0026). Every guest action is recorded in the link's activity, with the guest's name.
"""

import asyncio
import re
import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app import authz
from app.auth import passwords, tokens
from app.core import security_log
from app.db import attachments as attachment_store
from app.db import auth as audit
from app.db import notes as note_store
from app.db import notifications as notification_store
from app.db import projects as project_store
from app.db import share_links as store
from app.db.database import Database
from app.files import sniff
from app.services import attachments as attachment_service
from app.services import limits, live
from app.services import note_content as content
from app.services.auth import CurrentSession

LinkRow = store.LinkRow
EventRow = store.EventRow

PREFIX = "phv_shr_"
TOKEN = re.compile(r"^phv_shr_[A-Za-z0-9_-]{43}$")
SESSION_HOURS = 12
DEFAULT_DAYS = 30
MAX_DAYS = 365
MAX_CHOSEN = 200


class LinkError(Exception):
    """A share link that can't be made or used (message is safe to show)."""


class PinNeededError(Exception):
    """The link has a PIN and none, or the wrong one, was given."""


def _hash(token: str) -> str:
    return tokens.token_hash(token).hex()


# ---------------------------------------------------------------- managing links (members)


@dataclass(frozen=True, slots=True)
class NewLink:
    row: LinkRow
    url: str
    pin: str | None


@dataclass(frozen=True, slots=True)
class Boxes:
    """What the person making the link ticked."""

    name: str
    days: int
    with_pin: bool
    tasks_view: str
    task_ids: list[uuid.UUID]
    tasks_tick: bool
    note_ids: list[uuid.UUID]
    append_note_id: uuid.UUID | None
    list_ids: list[uuid.UUID]
    lists_tick: bool
    files_view: bool
    files_add: bool


async def _project_access(conn: Any, project_id: uuid.UUID) -> authz.ProjectAccess:
    access = authz.ProjectAccess(await project_store.role(conn, project_id))
    if access.role is not None and await project_store.get_project(conn, project_id) is None:
        return authz.ProjectAccess(None)
    return access


async def create_link(
    db: Database,
    session: CurrentSession,
    project_id: uuid.UUID,
    boxes: Boxes,
    base_url: str,
    ip: str | None,
) -> NewLink:
    if not 1 <= boxes.days <= MAX_DAYS:
        raise LinkError(f"A link can last from 1 day to {MAX_DAYS} days.")
    if boxes.tasks_tick and boxes.tasks_view == "none":
        raise LinkError("To tick tasks off, the link must show them.")
    if boxes.lists_tick and not boxes.list_ids:
        raise LinkError("Choose the lists whose items can be ticked off.")
    nothing = (
        boxes.tasks_view == "none"
        and not boxes.note_ids
        and boxes.append_note_id is None
        and not boxes.list_ids
        and not boxes.files_view
        and not boxes.files_add
    )
    if nothing:
        raise LinkError("Tick at least one thing the link can show or do.")
    token = tokens.new_token(PREFIX)
    pin = f"{secrets.randbelow(1_000_000):06d}" if boxes.with_pin else None
    pin_hash = await asyncio.to_thread(passwords.hash_password, pin) if pin else None
    async with db.user_transaction(session.user.id) as conn:
        access = await _project_access(conn, project_id)
        authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
        authz.require(session.principal, authz.Action.PROJECT_SHARE_LINK, access)
        chosen_tasks = boxes.task_ids if boxes.tasks_view == "chosen" else []
        notes = [*boxes.note_ids, *([boxes.append_note_id] if boxes.append_note_id else [])]
        if not (
            await store.all_in_project(conn, "tasks", project_id, chosen_tasks)
            and await store.all_in_project(conn, "notes", project_id, notes)
            and await store.all_in_project(conn, "lists", project_id, boxes.list_ids)
        ):
            raise LinkError("Something chosen isn't part of this project.")
        link_id = await store.create_link(
            conn,
            {
                "project_id": project_id,
                "created_by": session.user.id,
                "name": boxes.name,
                "token_hash": _hash(token),
                "pin_hash": pin_hash,
                "tasks_view": boxes.tasks_view,
                "tasks_tick": boxes.tasks_tick,
                "files_view": boxes.files_view,
                "files_add": boxes.files_add,
                "lists_tick": boxes.lists_tick,
                "append_note_id": boxes.append_note_id,
                "days": boxes.days,
            },
        )
        await store.add_items(conn, link_id, "task", chosen_tasks[:MAX_CHOSEN])
        await store.add_items(conn, link_id, "note", boxes.note_ids[:MAX_CHOSEN])
        await store.add_items(conn, link_id, "list", boxes.list_ids[:MAX_CHOSEN])
        await audit.record_audit(
            conn,
            action="share_link.created",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=project_id,
            resource_type="share_link",
            resource_id=link_id,
        )
        row = await store.get_link(conn, link_id)
    if row is None:
        raise RuntimeError("created link not visible")
    # The token goes after '#': browsers never send it to the server, proxies or Referer.
    return NewLink(row, f"{base_url.rstrip('/')}/s#{token}", pin)


async def links_for_project(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> list[tuple[LinkRow, dict[str, list[uuid.UUID]]]]:
    async with db.user_transaction(session.user.id) as conn:
        access = await _project_access(conn, project_id)
        authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
        authz.require(session.principal, authz.Action.PROJECT_EDIT, access)
        rows = await store.links_for_project(conn, project_id)
        return [(r, await store.items(conn, r.id)) for r in rows]


async def _link_access(conn: Any, session: CurrentSession, link_id: uuid.UUID) -> LinkRow:
    link = await store.get_link(conn, link_id)  # RLS: editors of its project only
    if link is None:
        raise authz.NotFoundError("Not found.")
    access = await _project_access(conn, link.project_id)
    authz.require(session.principal, authz.Action.PROJECT_VIEW, access)
    authz.require(session.principal, authz.Action.PROJECT_EDIT, access)
    return link


async def revoke(db: Database, session: CurrentSession, link_id: uuid.UUID, ip: str | None) -> None:
    async with db.user_transaction(session.user.id) as conn:
        link = await _link_access(conn, session, link_id)
        await store.revoke(conn, link_id)
        await audit.record_audit(
            conn,
            action="share_link.revoked",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=link.project_id,
            resource_type="share_link",
            resource_id=link_id,
        )
    async with db.system_transaction() as conn:
        await store.end_sessions(conn, link_id)


async def events(db: Database, session: CurrentSession, link_id: uuid.UUID) -> list[EventRow]:
    async with db.user_transaction(session.user.id) as conn:
        await _link_access(conn, session, link_id)
        return await store.events(conn, link_id)


# ---------------------------------------------------------------- guests


@dataclass(frozen=True, slots=True)
class Guest:
    grant: authz.LinkGrant
    name: str
    link_name: str


def _grant(link: LinkRow, items: dict[str, list[uuid.UUID]]) -> authz.LinkGrant:
    return authz.LinkGrant(
        link_id=link.id,
        project_id=link.project_id,
        tasks_view=link.tasks_view,
        tasks_tick=link.tasks_tick,
        files_view=link.files_view,
        files_add=link.files_add,
        lists_tick=link.lists_tick,
        append_note_id=link.append_note_id,
        task_ids=frozenset(items["task"]),
        note_ids=frozenset(items["note"]),
        list_ids=frozenset(items["list"]),
    )


def clean_name(name: str) -> str:
    name = " ".join(name.split())[:60]
    if not name:
        raise LinkError("Type your name.")
    return name


async def open_link(
    db: Database, token: str, guest_name: str, pin: str | None, ip: str | None
) -> tuple[str, datetime, str, str]:
    """(session token, when it ends, link name, project title) for a working link. Wrong or
    dead links all look the same: not found."""
    await limits.check(db, [(limits.SHARE_OPEN_IP, limits.key(limits.SHARE_OPEN_IP, ip))], ip=ip)
    name = clean_name(guest_name)
    if not TOKEN.match(token):
        security_log.event("share_link_failed", ip=ip, reason="malformed")
        raise authz.NotFoundError("This link doesn't work any more.")
    async with db.system_transaction() as conn:
        link = await store.live_link_by_token(conn, _hash(token))
    if link is None:
        # Unknown, expired or turned off: counted by fail2ban/CrowdSec like failed sign-ins.
        security_log.event("share_link_failed", ip=ip, reason="unknown")
        raise authz.NotFoundError("This link doesn't work any more.")
    if link.pin_hash is not None:
        if not pin:
            raise PinNeededError("This link needs its PIN.")
        await limits.check(
            db, [(limits.SHARE_PIN_LINK, limits.key(limits.SHARE_PIN_LINK, link.id))], ip=ip
        )
        if not await asyncio.to_thread(passwords.verify_password, link.pin_hash, pin):
            security_log.event("share_link_failed", ip=ip, reason="pin", link_id=str(link.id))
            raise PinNeededError("That PIN isn't right.")
    session_token = tokens.new_token()
    async with db.system_transaction() as conn:
        ends = await store.create_session(conn, _hash(session_token), link, name, SESSION_HOURS)
        await store.record(conn, link.id, name, "opened")
    async with db.link_transaction(link.id) as conn:
        title = await store.guest_project_title(conn, link.project_id) or ""
    return session_token, ends, link.name, title


async def guest_from_session(db: Database, session_token: str) -> Guest | None:
    if not session_token or len(session_token) > 100:
        return None
    async with db.system_transaction() as conn:
        found = await store.live_session(conn, _hash(session_token))
        if found is None:
            return None
        link, name = found
        items = await store.items(conn, link.id)
        await store.touch(conn, link.id)
    return Guest(_grant(link, items), name, link.name)


async def leave(db: Database, session_token: str) -> None:
    async with db.system_transaction() as conn:
        await store.end_session(conn, _hash(session_token))


@dataclass(frozen=True, slots=True)
class GuestView:
    link_name: str
    guest_name: str
    project_title: str
    grant: authz.LinkGrant
    tasks: list[dict[str, Any]]
    notes: list[dict[str, Any]]
    lists: list[dict[str, Any]]
    files: list[dict[str, Any]]


async def view(db: Database, guest: Guest) -> GuestView:
    """Everything the link shows, read in a link transaction (the database filters too)."""
    g = guest.grant
    async with db.link_transaction(g.link_id) as conn:
        title = await store.guest_project_title(conn, g.project_id) or ""
        tasks = (
            [
                {"id": t.id, "title": t.title, "notes": t.notes, "done": t.done_at is not None}
                for t in await store.guest_tasks(conn, g.project_id)
                if authz.link_allows(g, "task.read", t.id)
            ]
            if g.tasks_view != "none"
            else []
        )
        notes = []
        for n in await store.guest_notes(conn, g.project_id):
            if not authz.link_allows(g, "note.read", n.id):
                continue
            lines, _ = content.card_lines(
                n.content if isinstance(n.content, dict) else content.EMPTY
            )
            notes.append(
                {"id": n.id, "title": n.title, "lines": lines, "can_add": n.id == g.append_note_id}
            )
        items = await store.guest_list_items(conn, g.project_id)
        lists = [
            {
                "id": li.id,
                "title": li.title,
                "kind": li.kind,
                "items": [
                    {
                        "id": i.id,
                        "text": i.text,
                        "quantity": i.quantity,
                        "unit": i.unit,
                        "checked": i.checked_at is not None,
                    }
                    for i in items
                    if i.list_id == li.id
                ],
            }
            for li in await store.guest_lists(conn, g.project_id)
            if authz.link_allows(g, "list.read", li.id)
        ]
        files = (
            [
                {
                    "id": f.id,
                    "filename": f.filename,
                    "size": f.size,
                    "is_photo": f.thumb_sha256 is not None,
                }
                for f in await store.guest_files(conn, g.project_id)
            ]
            if g.files_view
            else []
        )
    return GuestView(guest.link_name, guest.name, title, g, tasks, notes, lists, files)


async def _write_limit(db: Database, guest: Guest, ip: str | None) -> None:
    await limits.check(
        db,
        [(limits.SHARE_WRITE_LINK, limits.key(limits.SHARE_WRITE_LINK, guest.grant.link_id))],
        ip=ip,
    )


async def _tell_creator(db: Database, guest: Guest) -> None:
    """The link's creator hears that it was used: at most once an hour per guest name
    (ADR 0018). Who and which link only; what they did is in the link's activity."""
    hour = datetime.now(UTC).strftime("%Y-%m-%dT%H")
    async with db.system_transaction() as conn:
        link = await store.get_link(conn, guest.grant.link_id)
        if link is None:
            return
        await notification_store.notify(
            conn,
            link.created_by,
            "share_link_used",
            {
                "guest": guest.name[:60],
                "link_name": link.name[:80],
                "project_id": str(link.project_id),
                "project_title": (await project_store.title(conn, link.project_id) or "")[:120],
            },
            f"share_link_used:{link.id}:{guest.name[:60]}:{hour}",
        )


async def tick_task(
    db: Database, guest: Guest, task_id: uuid.UUID, done: bool, ip: str | None
) -> None:
    authz.require_link(guest.grant, "task.tick", task_id)
    await _write_limit(db, guest, ip)
    async with db.link_transaction(guest.grant.link_id) as conn:
        title = await store.guest_tick_task(conn, guest.grant.project_id, task_id, done)
        if title is None:
            raise authz.NotFoundError("Not found.")
        await store.record(
            conn, guest.grant.link_id, guest.name, "task.done" if done else "task.undone", title
        )
    live.publish(guest.grant.project_id, "tasks")
    await _tell_creator(db, guest)


async def tick_item(
    db: Database, guest: Guest, item_id: uuid.UUID, checked: bool, ip: str | None
) -> None:
    await _write_limit(db, guest, ip)
    async with db.link_transaction(guest.grant.link_id) as conn:
        list_id = await store.list_of_item(conn, item_id)
        if list_id is None:
            raise authz.NotFoundError("Not found.")
        authz.require_link(guest.grant, "list.tick", list_id)
        text_ = await store.guest_tick_item(conn, guest.grant.project_id, item_id, checked)
        if text_ is None:
            raise authz.NotFoundError("Not found.")
        await store.record(
            conn,
            guest.grant.link_id,
            guest.name,
            "item.checked" if checked else "item.unchecked",
            text_,
        )
    live.publish(guest.grant.project_id, "lists")
    await _tell_creator(db, guest)


MAX_ADDITION = 4000


async def add_to_note(
    db: Database, guest: Guest, note_id: uuid.UUID, words: str, ip: str | None
) -> None:
    """Add to the one note the link allows: new paragraphs at the end, headed with who and
    when. What's already there is never changed."""
    authz.require_link(guest.grant, "note.append", note_id)
    words = words.strip()
    if not words:
        raise LinkError("Type something to add.")
    if len(words) > MAX_ADDITION:
        raise LinkError(f"Add at most {MAX_ADDITION} characters at a time.")
    await _write_limit(db, guest, ip)
    when = datetime.now(UTC).date().isoformat()
    heading = f"{guest.name} (via link “{guest.link_name}”), {when}:"
    added = [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": heading, "marks": [{"type": "bold"}]}],
        },
        *[
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            if line.strip()
            else {"type": "paragraph"}
            for line in words.split("\n")
        ],
    ]
    async with db.link_transaction(guest.grant.link_id) as conn:
        note = await note_store.get_note(conn, note_id)
        document = await note_store.get_content(conn, note_id)
        if note is None or note.project_id != guest.grant.project_id:
            raise authz.NotFoundError("Not found.")
        existing = document if document is not None else content.EMPTY
        try:
            updated = content.clean(
                {"type": "doc", "content": [*existing.get("content", []), *added]}
            )
        except content.ContentError:
            raise LinkError("This note is full: nothing more can be added to it.") from None
        if (
            await note_store.save(
                conn,
                note_id,
                expected_version=None,
                title=note.title,
                content=updated,
                text_content=content.to_markdown(updated),
            )
            is None
        ):
            raise authz.NotFoundError("Not found.")
        await store.record(conn, guest.grant.link_id, guest.name, "note.added", note.title)
    live.publish(guest.grant.project_id, "notes")
    await _tell_creator(db, guest)


_PHOTO_TYPES = {t.mime: t for t in (sniff.JPEG, sniff.PNG, sniff.GIF, sniff.WEBP)}


async def add_photo(
    db: Database,
    blobs: attachment_service.BlobStore,
    guest: Guest,
    *,
    filename: str,
    chunks: AsyncIterator[bytes],
    max_bytes: int,
    ip: str | None,
) -> uuid.UUID:
    """A photo from a guest: always cleaned (location removed), like any photo."""
    authz.require_link(guest.grant, "file.add")
    await limits.check(
        db,
        [
            (
                attachment_service.UPLOAD_LINK,
                limits.key(attachment_service.UPLOAD_LINK, guest.grant.link_id),
            )
        ],
        ip=ip,
    )
    photo, thumb, content_type = await attachment_service.clean_photo(
        blobs, chunks=chunks, max_bytes=max_bytes
    )
    size = await asyncio.to_thread(lambda: blobs.path(photo).stat().st_size)
    async with db.link_transaction(guest.grant.link_id) as conn:
        creator = await store.link_creator(conn)
        attachment_id = await attachment_store.create_attachment(
            conn,
            project_id=guest.grant.project_id,
            user_id=creator,
            filename=sniff.safe_filename(filename, _PHOTO_TYPES.get(content_type, sniff.JPEG)),
            kind="image",
            content_type=content_type,
            size=size,
            blob_sha256=photo,
            thumb_sha256=thumb,
            metadata_kept=False,
        )
        await store.record(conn, guest.grant.link_id, guest.name, "photo.added", filename[:200])
    live.publish(guest.grant.project_id, "attachments")
    await _tell_creator(db, guest)
    return attachment_id


async def file_for_guest(
    db: Database, guest: Guest, attachment_id: uuid.UUID, part: str
) -> tuple[str, str, str]:
    """(blob, content type, file name) of a file the link shows; part is view, thumbnail or
    download. Photos are shown cleaned; kept-location originals and other files download."""
    authz.require_link(guest.grant, "file.read")
    async with db.link_transaction(guest.grant.link_id) as conn:
        row = await attachment_store.get_attachment(conn, attachment_id)
    if row is None or row.project_id != guest.grant.project_id:
        raise authz.NotFoundError("Not found.")
    if part == "thumbnail":
        if row.thumb_sha256 is None:
            raise authz.NotFoundError("Not found.")
        return row.thumb_sha256, "image/webp", "thumbnail.webp"
    if part == "view":
        if row.thumb_sha256 is None or row.metadata_kept:
            raise authz.NotFoundError("Not found.")
        return row.blob_sha256, row.content_type, row.filename
    return row.blob_sha256, row.content_type, row.filename

"""Notes: open, edit, tap Done to save (owner decision 2026-09-28, docs/adr/0016).

No live co-editing and no automatic saving. A save sends the whole document with the version
it started from; if someone else saved in between, the save is refused (409) rather than
overwriting their work. The document is cleaned by the server before it's stored
(app/services/note_content.py), and the Markdown copy for previews and search is made from it.
"""

import uuid
from dataclasses import replace
from typing import Any

from app import authz
from app.db import auth as audit
from app.db import notes as store
from app.db import projects as project_store
from app.db.database import Database
from app.services import live
from app.services import note_content as content
from app.services.auth import CurrentSession
from app.services.note_content import ContentError
from app.services.projects import ConflictError

NoteRow = store.NoteRow
MAX_TEXT_CONTENT = content.MAX_TEXT
MAX_CARD_NOTES = 50

__all__ = ["ConflictError", "ContentError", "NoteRow"]


class ChecklistChangedError(Exception):
    """The checklist changed since the page was loaded (message is safe to show)."""


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


async def _document(conn: Any, note_id: uuid.UUID) -> dict[str, Any]:
    """The note's document; notes from the earlier live editor are converted on the fly."""
    document = await store.get_content(conn, note_id)
    if document is not None:
        return document
    snapshot, updates = await store.load_state(conn, note_id)
    return content.from_legacy(snapshot, updates) or content.EMPTY


async def notes_for_project(
    db: Database, session: CurrentSession, project_id: uuid.UUID, *, archived: bool = False
) -> list[NoteRow]:
    async with db.user_transaction(session.user.id) as conn:
        _require(session, await _access(conn, project_id), write=False)
        notes = await store.notes_for_project(conn, project_id, archived=archived)
        # Notes from the earlier live editor: their stored preview text may hold leftovers of
        # the old garbled-text bug, so it's rebuilt from the document until the note is saved.
        legacy = await store.unconverted(conn, project_id)
        return [
            replace(n, text_content=content.to_markdown(await _document(conn, n.id))[:300])
            if n.id in legacy
            else n
            for n in notes
        ]


async def create_note(
    db: Database,
    session: CurrentSession,
    project_id: uuid.UUID,
    title: str,
    ip: str | None,
    *,
    source: str = "user",
) -> NoteRow:
    """`source`: who wrote it (`mcp:<app>` for an AI app, A§12.4)."""
    async with db.user_transaction(session.user.id) as conn:
        _require(session, await _access(conn, project_id), write=True)
        note_id = await store.create_note(
            conn, project_id=project_id, user_id=session.user.id, title=title, source=source[:120]
        )
        await store.save(
            conn,
            note_id,
            expected_version=None,
            title=title,
            content=content.EMPTY,
            text_content="",
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
) -> tuple[NoteRow, bool, dict[str, Any]]:
    """The note, whether the caller may edit it, and its document."""
    async with db.user_transaction(session.user.id) as conn:
        note, access = await _note_access(conn, note_id)
        _require(session, access, write=False)
        document = await _document(conn, note_id)
    return note, authz.allowed(session.principal, authz.Action.PROJECT_EDIT, access), document


async def save(
    db: Database,
    session: CurrentSession,
    note_id: uuid.UUID,
    *,
    expected_version: int,
    title: str,
    document: Any,
    ip: str | None,
) -> NoteRow:
    """Done: store the title and the whole document, if nobody saved since it was opened."""
    cleaned = content.clean(document)  # ContentError for anything not allowed
    async with db.user_transaction(session.user.id) as conn:
        note, access = await _note_access(conn, note_id)
        _require(session, access, write=True)
        version = await store.save(
            conn,
            note_id,
            expected_version=expected_version,
            title=title,
            content=cleaned,
            text_content=content.to_markdown(cleaned),
        )
        if version is None:
            raise ConflictError(
                "Someone else saved this note since you opened it. Your changes weren't saved."
            )
        await audit.record_audit(
            conn,
            action="note.saved",
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


async def set_archived(
    db: Database, session: CurrentSession, note_id: uuid.UUID, archived: bool, ip: str | None
) -> None:
    async with db.user_transaction(session.user.id) as conn:
        note, access = await _note_access(conn, note_id)
        _require(session, access, write=True)
        await store.set_archived(conn, note_id, archived)
        await audit.record_audit(
            conn,
            action="note.archived" if archived else "note.unarchived",
            actor_user_id=session.user.id,
            ip=ip,
            project_id=note.project_id,
            resource_type="note",
            resource_id=note_id,
        )
    live.publish(note.project_id, "notes")


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


# ---------------------------------------------------------------- checkboxes on the project page


async def project_note_cards(
    db: Database, session: CurrentSession, project_id: uuid.UUID
) -> list[tuple[NoteRow, list[dict[str, Any]], int]]:
    """What the project page shows on each note's card: its lines in order, with checkboxes
    that can be ticked there, and how many lines didn't fit."""
    async with db.user_transaction(session.user.id) as conn:
        _require(session, await _access(conn, project_id), write=False)
        notes = await store.notes_for_project(conn, project_id)
        result = []
        for note in notes[:MAX_CARD_NOTES]:
            lines, more = content.card_lines(await _document(conn, note.id))
            result.append((note, lines, more))
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
        try:
            document = content.with_checked(await _document(conn, note_id), index, text, checked)
        except ContentError as exc:
            raise ChecklistChangedError(str(exc)) from None
        await store.save(
            conn,
            note_id,
            expected_version=None,
            title=note.title,
            content=document,
            text_content=content.to_markdown(document),
        )
    live.publish(note.project_id, "notes")

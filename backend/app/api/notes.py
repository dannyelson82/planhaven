"""Notes: list, create, open, save on Done, delete; checkboxes on the project page.

A save sends the title and the whole editor document with `If-Match` (the version it was
opened at); if someone else saved in between it's refused with 409. The server cleans the
document before storing it (app/services/note_content.py).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.api.projects import _etag, _version
from app.services import notes as service
from app.services.notes import ConflictError, ContentError

router = APIRouter(prefix="/api/v1")

Title = Annotated[str, Field(min_length=1, max_length=200)]


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title


class NoteSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title
    # Checked in full by the server (allowlist of node types, marks and attributes; size and
    # depth limits); the request body limit caps its size first.
    content: dict[str, Any]


class NoteOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    text_content: str
    source: str
    updated_at: datetime
    version: int
    can_edit: bool = False
    content: dict[str, Any] | None = None


def _note(
    n: service.NoteRow, can_edit: bool = False, document: dict[str, Any] | None = None
) -> NoteOut:
    return NoteOut(
        id=n.id,
        project_id=n.project_id,
        title=n.title,
        text_content=n.text_content,
        source=n.source,
        updated_at=n.updated_at,
        version=n.version,
        can_edit=can_edit,
        content=document,
    )


@router.get("/projects/{project_id}/notes")
async def list_notes(project_id: uuid.UUID, session: SessionDep, request: Request) -> list[NoteOut]:
    rows = await service.notes_for_project(deps.database(request), session, project_id)
    return [_note(n) for n in rows]


@router.post("/projects/{project_id}/notes", status_code=201)
async def create_note(
    project_id: uuid.UUID, body: NoteIn, session: SessionDep, request: Request, response: Response
) -> NoteOut:
    note = await service.create_note(
        deps.database(request), session, project_id, body.title, deps.client_ip(request)
    )
    _etag(response, note.version)
    return _note(note, can_edit=True)


@router.get("/notes/{note_id}")
async def get_note(
    note_id: uuid.UUID, session: SessionDep, request: Request, response: Response
) -> NoteOut:
    note, can_edit, document = await service.get_note(deps.database(request), session, note_id)
    _etag(response, note.version)
    return _note(note, can_edit, document)


@router.put("/notes/{note_id}")
async def save_note(
    note_id: uuid.UUID,
    body: NoteSave,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> NoteOut:
    try:
        note = await service.save(
            deps.database(request),
            session,
            note_id,
            expected_version=_version(if_match),
            title=body.title,
            document=body.content,
            ip=deps.client_ip(request),
        )
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    except ContentError as exc:
        raise HTTPException(422, str(exc)) from None
    _etag(response, note.version)
    return _note(note, can_edit=True)


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_note(deps.database(request), session, note_id, deps.client_ip(request))


class CardLineOut(BaseModel):
    kind: Literal["text", "heading", "bullet", "check"]
    text: str
    depth: int
    marker: str | None = None
    index: int | None = None
    checked: bool | None = None


class NoteCardOut(BaseModel):
    note_id: uuid.UUID
    lines: list[CardLineOut]
    more: int


class TickIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: Annotated[int, Field(ge=0, le=10_000)]
    text: Annotated[str, Field(max_length=300)]
    checked: bool


@router.get("/projects/{project_id}/note-cards")
async def note_cards(
    project_id: uuid.UUID, session: SessionDep, request: Request
) -> list[NoteCardOut]:
    rows = await service.project_note_cards(deps.database(request), session, project_id)
    return [
        NoteCardOut(note_id=note.id, lines=[CardLineOut(**line) for line in lines], more=more)
        for note, lines, more in rows
    ]


@router.post("/notes/{note_id}/checklist", status_code=204)
async def tick(note_id: uuid.UUID, body: TickIn, session: SessionDep, request: Request) -> None:
    try:
        await service.set_checked(
            deps.database(request), session, note_id, body.index, body.text, body.checked
        )
    except service.ChecklistChangedError as exc:
        raise HTTPException(409, str(exc)) from None

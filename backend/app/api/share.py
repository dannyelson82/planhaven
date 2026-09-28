"""What a guest with a share link sees and does (ADR 0015). No account: a short-lived link
session (cookie) set when the link is opened, and only what the link was given."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.attachments import _file
from app.services import attachments as attachment_service
from app.services import share_links as service

router = APIRouter(prefix="/api/v1/share", tags=["share (guests)"])

Guest = Annotated[Any, Depends(deps.require_share_session)]


class OpenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: Annotated[str, Field(max_length=100)]
    name: Annotated[str, Field(min_length=1, max_length=60)]
    pin: Annotated[str | None, Field(max_length=6, pattern=r"^\d{6}$")] = None


class OpenedOut(BaseModel):
    link_name: str
    project_title: str


@router.post("/open", dependencies=[deps.SameOrigin])
async def open_link(body: OpenIn, request: Request, response: Response) -> OpenedOut:
    """Open a link: the token (from after '#' in the link), the guest's name, and the PIN
    if the link has one. Sets the link session cookie."""
    try:
        token, ends, link_name, title = await service.open_link(
            deps.database(request), body.token, body.name, body.pin, deps.client_ip(request)
        )
    except service.PinNeededError as exc:
        raise HTTPException(401, str(exc)) from None
    except service.LinkError as exc:
        raise HTTPException(422, str(exc)) from None
    s = deps.settings(request)
    response.set_cookie(
        deps.share_cookie_name(s),
        token,
        max_age=max(60, int((ends - datetime.now(UTC)).total_seconds())),
        path="/",
        secure=s.base_scheme == "https",
        httponly=True,
        samesite="strict",
    )
    return OpenedOut(link_name=link_name, project_title=title)


@router.post("/leave", status_code=204, dependencies=[deps.SameOrigin])
async def leave(request: Request, response: Response) -> None:
    s = deps.settings(request)
    await service.leave(deps.database(request), request.cookies.get(deps.share_cookie_name(s), ""))
    response.delete_cookie(deps.share_cookie_name(s), path="/")


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    notes: str
    done: bool


class NoteOut(BaseModel):
    id: uuid.UUID
    title: str
    lines: list[dict[str, Any]]
    can_add: bool


class ItemOut(BaseModel):
    id: uuid.UUID
    text: str
    quantity: Decimal | None
    unit: str | None
    checked: bool


class ListOut(BaseModel):
    id: uuid.UUID
    title: str
    kind: str
    items: list[ItemOut]


class FileOut(BaseModel):
    id: uuid.UUID
    filename: str
    size: int
    is_photo: bool


class Allowed(BaseModel):
    tick_tasks: bool
    tick_items: bool
    add_photos: bool


class ViewOut(BaseModel):
    link_name: str
    guest_name: str
    project_title: str
    allowed: Allowed
    tasks: list[TaskOut]
    notes: list[NoteOut]
    lists: list[ListOut]
    files: list[FileOut]
    files_shown: bool


@router.get("/view")
async def view(guest: Guest, request: Request) -> ViewOut:
    v = await service.view(deps.database(request), guest)
    return ViewOut(
        link_name=v.link_name,
        guest_name=v.guest_name,
        project_title=v.project_title,
        allowed=Allowed(
            tick_tasks=v.grant.tasks_tick,
            tick_items=v.grant.lists_tick,
            add_photos=v.grant.files_add,
        ),
        tasks=[TaskOut(**t) for t in v.tasks],
        notes=[NoteOut(**n) for n in v.notes],
        lists=[ListOut(**li) for li in v.lists],
        files=[FileOut(**f) for f in v.files],
        files_shown=v.grant.files_view,
    )


class Done(BaseModel):
    model_config = ConfigDict(extra="forbid")
    done: bool


class Checked(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checked: bool


class Addition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Annotated[str, Field(min_length=1, max_length=service.MAX_ADDITION)]


@router.post("/tasks/{task_id}", status_code=204)
async def tick_task(task_id: uuid.UUID, body: Done, guest: Guest, request: Request) -> None:
    await service.tick_task(
        deps.database(request), guest, task_id, body.done, deps.client_ip(request)
    )


@router.post("/list-items/{item_id}", status_code=204)
async def tick_item(item_id: uuid.UUID, body: Checked, guest: Guest, request: Request) -> None:
    await service.tick_item(
        deps.database(request), guest, item_id, body.checked, deps.client_ip(request)
    )


@router.post("/notes/{note_id}/add", status_code=204)
async def add_to_note(note_id: uuid.UUID, body: Addition, guest: Guest, request: Request) -> None:
    try:
        await service.add_to_note(
            deps.database(request), guest, note_id, body.text, deps.client_ip(request)
        )
    except service.LinkError as exc:
        raise HTTPException(422, str(exc)) from None


class Added(BaseModel):
    id: uuid.UUID


@router.post("/files", status_code=201)
async def add_photo(
    guest: Guest,
    request: Request,
    filename: Annotated[str, Query(min_length=1, max_length=255)] = "photo.jpg",
) -> Added:
    """A photo from the guest; the raw request body, like other uploads."""
    try:
        attachment_id = await service.add_photo(
            deps.database(request),
            deps.blobs(request),
            guest,
            filename=filename,
            chunks=request.stream(),
            max_bytes=deps.settings(request).max_upload_mb * 1024 * 1024,
            ip=deps.client_ip(request),
        )
    except attachment_service.UploadTooLargeError:
        raise HTTPException(413, "This file is larger than the upload limit.") from None
    except attachment_service.UnsupportedFileError as exc:
        raise HTTPException(415, str(exc)) from None
    return Added(id=attachment_id)


@router.get("/files/{attachment_id}/{part}")
async def get_file(
    attachment_id: uuid.UUID,
    part: Annotated[Literal["view", "thumbnail", "download"], Path()],
    guest: Guest,
    request: Request,
) -> FileResponse:
    sha, content_type, name = await service.file_for_guest(
        deps.database(request), guest, attachment_id, part
    )
    if part == "download":
        return _file(request, sha, "application/octet-stream", "attachment", name)
    return _file(request, sha, content_type, "inline", name)

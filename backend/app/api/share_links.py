"""Share links for people without an account (ADR 0015): making, listing and revoking them
(project owners and editors), and the link's activity."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.services import share_links as service

router = APIRouter(prefix="/api/v1", tags=["share links"])

Ids = Annotated[list[uuid.UUID], Field(max_length=service.MAX_CHOSEN)]


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=100)]
    days: Annotated[int, Field(ge=1, le=service.MAX_DAYS)] = service.DEFAULT_DAYS
    pin: bool = False  # off by default (owner decision)
    tasks_view: Literal["none", "all", "chosen"] = "none"
    task_ids: Ids = []
    tasks_tick: bool = False
    note_ids: Ids = []
    append_note_id: uuid.UUID | None = None
    list_ids: Ids = []
    lists_tick: bool = False
    files_view: bool = False
    files_add: bool = False


class LinkOut(BaseModel):
    id: uuid.UUID
    name: str
    has_pin: bool
    tasks_view: str
    task_ids: list[uuid.UUID]
    tasks_tick: bool
    note_ids: list[uuid.UUID]
    append_note_id: uuid.UUID | None
    list_ids: list[uuid.UUID]
    lists_tick: bool
    files_view: bool
    files_add: bool
    created_at: datetime
    expires_at: datetime
    revoked: bool
    last_used_at: datetime | None


class NewLinkOut(LinkOut):
    url: str  # shown once; only a hash is kept
    pin: str | None  # shown once


class EventOut(BaseModel):
    at: datetime
    guest_name: str
    action: str
    detail: str


def _out(link: service.LinkRow, items: dict[str, list[uuid.UUID]]) -> LinkOut:
    return LinkOut(
        id=link.id,
        name=link.name,
        has_pin=link.pin_hash is not None,
        tasks_view=link.tasks_view,
        task_ids=items["task"],
        tasks_tick=link.tasks_tick,
        note_ids=items["note"],
        append_note_id=link.append_note_id,
        list_ids=items["list"],
        lists_tick=link.lists_tick,
        files_view=link.files_view,
        files_add=link.files_add,
        created_at=link.created_at,
        expires_at=link.expires_at,
        revoked=link.revoked_at is not None,
        last_used_at=link.last_used_at,
    )


@router.get("/projects/{project_id}/share-links")
async def list_links(project_id: uuid.UUID, session: SessionDep, request: Request) -> list[LinkOut]:
    rows = await service.links_for_project(deps.database(request), session, project_id)
    return [_out(link, items) for link, items in rows]


@router.post("/projects/{project_id}/share-links", status_code=201)
async def create_link(
    project_id: uuid.UUID, body: LinkIn, session: SessionDep, request: Request
) -> NewLinkOut:
    boxes = service.Boxes(
        name=" ".join(body.name.split()),
        days=body.days,
        with_pin=body.pin,
        tasks_view=body.tasks_view,
        task_ids=body.task_ids,
        tasks_tick=body.tasks_tick,
        note_ids=body.note_ids,
        append_note_id=body.append_note_id,
        list_ids=body.list_ids,
        lists_tick=body.lists_tick,
        files_view=body.files_view,
        files_add=body.files_add,
    )
    try:
        new = await service.create_link(
            deps.database(request),
            session,
            project_id,
            boxes,
            deps.settings(request).base_url,
            deps.client_ip(request),
        )
    except service.LinkError as exc:
        raise HTTPException(422, str(exc)) from None
    items = {
        "task": body.task_ids if body.tasks_view == "chosen" else [],
        "note": body.note_ids,
        "list": body.list_ids,
    }
    return NewLinkOut(**_out(new.row, items).model_dump(), url=new.url, pin=new.pin)


@router.post("/share-links/{link_id}/revoke", status_code=204)
async def revoke_link(link_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.revoke(deps.database(request), session, link_id, deps.client_ip(request))


@router.get("/share-links/{link_id}/events")
async def link_events(link_id: uuid.UUID, session: SessionDep, request: Request) -> list[EventOut]:
    rows = await service.events(deps.database(request), session, link_id)
    return [
        EventOut(at=e.at, guest_name=e.guest_name, action=e.action, detail=e.detail) for e in rows
    ]

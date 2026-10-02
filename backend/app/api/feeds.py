"""The calendar feed (`/ics/<key>.ics`), Reminders sync for the iPhone Shortcut
(`/api/v1/sync/*`, with a sync key), and managing those keys and synced lists."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.services import feeds as service
from app.services import lists as list_service

router = APIRouter()
SyncKey = Annotated[Any, Depends(deps.require_sync_key)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- the calendar feed


@router.get("/ics/{key}.ics", include_in_schema=False)
async def calendar_feed(key: Annotated[str, Path(max_length=120)], request: Request) -> Response:
    """Read-only, the key in the URL (calendar apps can't send headers); unknown keys get 404."""
    holder = await service.authenticate(deps.database(request), "ics", key, deps.client_ip(request))
    if holder is None:
        raise HTTPException(404)
    body = await service.feed(deps.database(request), holder)
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "private, max-age=900",
            "Content-Disposition": 'inline; filename="planhaven.ics"',
            "Referrer-Policy": "no-referrer",
        },
    )


# ---------------------------------------------------------------- Reminders sync (Shortcut)


class SyncItemOut(BaseModel):
    id: uuid.UUID
    list: str
    title: str
    done: bool
    removed: bool
    url: str
    # For the Shortcut: "show" (keep or add it in Reminders) or "remove" (ticked or deleted).
    action: Literal["show", "remove"]


class PullOut(BaseModel):
    cursor: str
    items: list[SyncItemOut]


class PushIn(Strict):
    done: Annotated[list[uuid.UUID], Field(max_length=service.MAX_PUSH)] = []
    undone: Annotated[list[uuid.UUID], Field(max_length=service.MAX_PUSH)] = []
    # The Shortcut's simpler form: the ticked reminders' notes (or their links) as one text;
    # every item id in it counts as done.
    done_text: Annotated[str, Field(max_length=40_000)] = ""


class PushOut(BaseModel):
    changed: int


@router.get("/api/v1/sync/pull")
async def sync_pull(
    holder: SyncKey,
    request: Request,
    cursor: Annotated[str | None, Query(max_length=64)] = None,
    list: Annotated[str | None, Query(max_length=60)] = None,
) -> PullOut:
    try:
        result = await service.pull(deps.database(request), holder, cursor, list)
    except service.FeedError as exc:
        raise HTTPException(422, str(exc)) from None
    base = deps.settings(request).base_url.rstrip("/")
    return PullOut(
        cursor=result.cursor,
        items=[
            SyncItemOut(
                id=i.id,
                list=i.list,
                title=i.title,
                done=i.done,
                removed=i.removed,
                url=f"{base}/i/{i.id}",
                action="remove" if i.done or i.removed else "show",
            )
            for i in result.items
        ],
    )


@router.post("/api/v1/sync/push")
async def sync_push(body: PushIn, holder: SyncKey, request: Request) -> PushOut:
    try:
        changed = await service.push(
            deps.database(request),
            holder,
            done=[*body.done, *service.ids_in(body.done_text)],
            undone=body.undone,
            ip=deps.client_ip(request),
        )
    except service.FeedError as exc:
        raise HTTPException(422, str(exc)) from None
    return PushOut(changed=changed)


# ---------------------------------------------------------------- managing keys (Account)


class KeyOut(BaseModel):
    id: uuid.UUID
    kind: str
    label: str
    details: bool
    created_at: datetime
    last_used_at: datetime | None


class NewKeyOut(KeyOut):
    key: str  # shown once
    url: str | None = None  # the feed link, for a calendar key


class KeyIn(Strict):
    kind: Literal["ics", "sync"]
    label: Annotated[str, Field(max_length=80)] = ""
    details: bool = False


class DetailsIn(Strict):
    details: bool


def _key(k: service.TokenRow) -> KeyOut:
    return KeyOut(
        id=k.id,
        kind=k.kind,
        label=k.label,
        details=k.details,
        created_at=k.created_at,
        last_used_at=k.last_used_at,
    )


@router.get("/api/v1/keys")
async def list_keys(session: SessionDep, request: Request) -> list[KeyOut]:
    return [_key(k) for k in await service.keys(deps.database(request), session)]


@router.post("/api/v1/keys", status_code=201)
async def make_key(body: KeyIn, session: SessionDep, request: Request) -> NewKeyOut:
    try:
        made = await service.make_key(
            deps.database(request),
            session,
            kind=body.kind,
            label=body.label,
            details=body.details,
            ip=deps.client_ip(request),
        )
    except service.FeedError as exc:
        raise HTTPException(422, str(exc)) from None
    base = deps.settings(request).base_url.rstrip("/")
    url = f"{base}/ics/{made.token}.ics" if body.kind == "ics" else None
    return NewKeyOut(**_key(made.row).model_dump(), key=made.token, url=url)


@router.delete("/api/v1/keys/{key_id}", status_code=204)
async def revoke_key(key_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.revoke_key(deps.database(request), session, key_id, deps.client_ip(request))


@router.put("/api/v1/keys/feed-details", status_code=204)
async def feed_details(body: DetailsIn, session: SessionDep, request: Request) -> None:
    await service.set_feed_details(deps.database(request), session, body.details)


class SyncListOut(BaseModel):
    list_id: uuid.UUID
    title: str
    reminders_name: str


class SyncIn(Strict):
    reminders_name: Annotated[str, Field(min_length=1, max_length=60)] | None


class ItemListOut(BaseModel):
    list_id: uuid.UUID


@router.get("/api/v1/sync/lists")
async def synced_lists(session: SessionDep, request: Request) -> list[SyncListOut]:
    rows = await service.synced_lists(deps.database(request), session)
    return [SyncListOut.model_validate(r, from_attributes=True) for r in rows]


@router.put("/api/v1/lists/{list_id}/sync", status_code=204)
async def set_sync(list_id: uuid.UUID, body: SyncIn, session: SessionDep, request: Request) -> None:
    await service.set_sync(deps.database(request), session, list_id, body.reminders_name)


@router.get("/api/v1/list-items/{item_id}/list")
async def item_list(item_id: uuid.UUID, session: SessionDep, request: Request) -> ItemListOut:
    """Where a Reminders link (`/i/<item>`) opens: the item's list."""
    return ItemListOut(
        list_id=await list_service.list_of_item(deps.database(request), session, item_id)
    )

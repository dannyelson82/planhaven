"""The change feed for the iPhone app's offline copy (ADR 0021, phase 0.5 milestone 3).

GET /api/v1/changes/snapshot: everything you can see, page by page (the first page says where
the feed starts). GET /api/v1/changes?cursor=...: what changed since. Works with a browser
session or the app's token.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api import deps
from app.api.deps import SessionDep
from app.api.errors import problem
from app.services import changes as service

router = APIRouter(prefix="/api/v1", tags=["changes"])

Limit = Annotated[int, Query(ge=1, le=service.PAGE)]


class ChangeOut(BaseModel):
    kind: str
    id: uuid.UUID
    op: str  # upsert, delete, access_gained (take a snapshot of it), access_lost (drop it)
    project_id: uuid.UUID | None
    asset_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    data: dict[str, Any] | None  # an upsert's current fields


class ChangesOut(BaseModel):
    changes: list[ChangeOut]
    cursor: str
    more: bool


class SnapshotOut(BaseModel):
    items: list[ChangeOut]
    after: str | None  # pass back for the next page; null when done
    changes_cursor: str | None  # first page only: where to start the feed


def _out(c: service.Change) -> ChangeOut:
    return ChangeOut.model_validate(c, from_attributes=True)


@router.get("/changes", response_model=None)
async def changes(
    session: SessionDep,
    request: Request,
    cursor: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Limit = service.PAGE,
) -> ChangesOut | JSONResponse:
    try:
        result = await service.since(deps.database(request), session, cursor, limit)
    except service.CursorError:
        raise HTTPException(400, "Not a change cursor; take a snapshot first.") from None
    except service.CursorExpiredError:
        return problem(410, "This cursor is too old. Take a new snapshot.")
    return ChangesOut(
        changes=[_out(c) for c in result.changes], cursor=result.cursor, more=result.more
    )


@router.get("/changes/snapshot")
async def snapshot(
    session: SessionDep,
    request: Request,
    after: Annotated[str | None, Query(max_length=100)] = None,
    project_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    limit: Limit = service.PAGE,
) -> SnapshotOut:
    scopes = [
        (k, v)
        for k, v in (("project", project_id), ("asset", asset_id), ("contact", contact_id))
        if v
    ]
    if len(scopes) > 1:
        raise HTTPException(400, "Choose one of project_id, asset_id or contact_id.")
    try:
        result = await service.snapshot(
            deps.database(request),
            session,
            after=after,
            scope=scopes[0] if scopes else None,
            limit=limit,
        )
    except service.CursorError:
        raise HTTPException(400, "Not a snapshot position.") from None
    return SnapshotOut(
        items=[_out(c) for c in result.items],
        after=result.after,
        changes_cursor=result.changes_cursor,
    )

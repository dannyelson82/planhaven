"""The person's side of AI apps (ADR 0019): connected apps, suggestions waiting for approval,
and recent AI changes with undo."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, ConfigDict

from app.api import deps
from app.api.deps import SessionDep
from app.services import ai_tools
from app.services import oauth as oauth_service

router = APIRouter(prefix="/api/v1/ai")
Id = Annotated[uuid.UUID, Path()]


class ConnectionOut(BaseModel):
    id: uuid.UUID
    client_name: str
    scope: str
    write_mode: str
    created_at: datetime
    last_used_at: datetime | None


class ConnectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["read", "write"]
    write_mode: Literal["approve", "apply"]


class SuggestionOut(BaseModel):
    id: uuid.UUID
    client_name: str
    project_id: uuid.UUID | None
    tool: str
    summary: str
    created_at: datetime


class ChangeOut(BaseModel):
    id: uuid.UUID
    client_name: str
    project_id: uuid.UUID | None
    kind: str
    summary: str
    created_at: datetime
    undone_at: datetime | None


class StatusOut(BaseModel):
    status: str


class CountOut(BaseModel):
    approved: int
    failed: int


def _conn(g: Any) -> ConnectionOut:
    return ConnectionOut(
        id=g.id,
        client_name=g.client_name,
        scope=g.scope,
        write_mode=g.write_mode,
        created_at=g.created_at,
        last_used_at=g.last_used_at,
    )


@router.get("/connections")
async def connections(session: SessionDep, request: Request) -> list[ConnectionOut]:
    return [_conn(g) for g in await oauth_service.connections(deps.database(request), session)]


@router.patch("/connections/{grant_id}", status_code=204)
async def change_connection(
    grant_id: Id, body: ConnectionIn, session: SessionDep, request: Request
) -> None:
    await oauth_service.change(
        deps.database(request), session, grant_id, scope=body.scope, write_mode=body.write_mode
    )


@router.delete("/connections/{grant_id}", status_code=204)
async def disconnect(grant_id: Id, session: SessionDep, request: Request) -> None:
    await oauth_service.disconnect(
        deps.database(request), session, grant_id, deps.client_ip(request)
    )


@router.get("/suggestions")
async def suggestions(session: SessionDep, request: Request) -> list[SuggestionOut]:
    rows = await ai_tools.pending(deps.database(request), session)
    return [
        SuggestionOut(
            id=s.id,
            client_name=s.client_name,
            project_id=s.project_id,
            tool=s.tool,
            summary=s.summary,
            created_at=s.created_at,
        )
        for s in rows
    ]


@router.post("/suggestions/{suggestion_id}/approve")
async def approve(suggestion_id: Id, session: SessionDep, request: Request) -> StatusOut:
    status = await ai_tools.decide(deps.database(request), session, suggestion_id, approve=True)
    return StatusOut(status=status)


@router.post("/suggestions/{suggestion_id}/decline")
async def decline(suggestion_id: Id, session: SessionDep, request: Request) -> StatusOut:
    status = await ai_tools.decide(deps.database(request), session, suggestion_id, approve=False)
    return StatusOut(status=status)


@router.post("/suggestions/approve-all")
async def approve_all(session: SessionDep, request: Request) -> CountOut:
    db = deps.database(request)
    approved = failed = 0
    for s in await ai_tools.pending(db, session):
        if await ai_tools.decide(db, session, s.id, approve=True) == "approved":
            approved += 1
        else:
            failed += 1
    return CountOut(approved=approved, failed=failed)


@router.get("/changes")
async def changes(session: SessionDep, request: Request) -> list[ChangeOut]:
    rows = await ai_tools.changes(deps.database(request), session)
    return [
        ChangeOut(
            id=c.id,
            client_name=c.client_name,
            project_id=c.project_id,
            kind=c.kind,
            summary=c.summary,
            created_at=c.created_at,
            undone_at=c.undone_at,
        )
        for c in rows
    ]


@router.post("/changes/{change_id}/undo", status_code=204)
async def undo(change_id: Id, session: SessionDep, request: Request) -> None:
    await ai_tools.undo(deps.database(request), session, change_id)

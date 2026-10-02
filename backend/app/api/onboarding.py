"""The welcome tour and "What's new": what the signed-in person has seen."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.services import onboarding as service

router = APIRouter(prefix="/api/v1")

Version = Annotated[str, Field(pattern=r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")]


class StateOut(BaseModel):
    welcome_done: bool
    whats_new_seen: str | None
    member_since: datetime | None


class StateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    welcome_done: bool = False
    whats_new_seen: Version | None = None


@router.get("/onboarding")
async def get_state(session: SessionDep, request: Request) -> StateOut:
    s = await service.get(deps.database(request), session)
    return StateOut(
        welcome_done=s.welcome_done, whats_new_seen=s.whats_new_seen, member_since=s.member_since
    )


@router.put("/onboarding")
async def put_state(body: StateIn, session: SessionDep, request: Request) -> StateOut:
    s = await service.update(
        deps.database(request),
        session,
        welcome_done=body.welcome_done,
        whats_new_seen=body.whats_new_seen,
    )
    return StateOut(
        welcome_done=s.welcome_done, whats_new_seen=s.whats_new_seen, member_since=s.member_since
    )

"""Trash: list what you deleted (or could restore) in the last 30 days, and restore it."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api import deps
from app.api.deps import SessionDep
from app.services import trash as service

router = APIRouter(prefix="/api/v1", tags=["trash"])


class TrashItem(BaseModel):
    kind: str
    id: uuid.UUID
    title: str
    project_id: uuid.UUID | None
    project_title: str | None
    deleted_at: datetime


@router.get("/trash")
async def list_trash(session: SessionDep, request: Request) -> list[TrashItem]:
    rows = await service.list_trash(deps.database(request), session)
    return [TrashItem.model_validate(r, from_attributes=True) for r in rows]


@router.post("/trash/{kind}/{item_id}/restore", status_code=204)
async def restore(
    kind: service.Kind, item_id: uuid.UUID, session: SessionDep, request: Request
) -> None:
    await service.restore(deps.database(request), session, kind, item_id, deps.client_ip(request))

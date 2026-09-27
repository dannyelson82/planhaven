"""The signed-in user's notifications."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api import deps
from app.api.deps import SessionDep
from app.services import notifications as service

router = APIRouter(prefix="/api/v1/notifications")


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    data: dict[str, Any]
    created_at: datetime
    read: bool


@router.get("")
async def list_notifications(session: SessionDep, request: Request) -> list[NotificationOut]:
    items = await service.list_own(deps.database(request), session)
    return [
        NotificationOut(id=n.id, kind=n.kind, data=n.data, created_at=n.created_at, read=n.read)
        for n in items
    ]


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(notification_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    if not await service.mark_read(deps.database(request), session, notification_id):
        raise HTTPException(404)

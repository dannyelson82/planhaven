"""Items a task needs, picked from the project's lists."""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.services import task_needs as service

router = APIRouter(prefix="/api/v1", tags=["tasks"])


class NeedOut(BaseModel):
    task_id: uuid.UUID
    list_item_id: uuid.UUID
    text: str
    quantity: Decimal | None
    unit: str | None
    checked: bool
    list_id: uuid.UUID
    list_title: str


class NeedsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_ids: Annotated[list[uuid.UUID], Field(max_length=service.MAX_NEEDS)]


@router.get("/projects/{project_id}/task-needs")
async def list_needs(project_id: uuid.UUID, session: SessionDep, request: Request) -> list[NeedOut]:
    rows = await service.needs_for_project(deps.database(request), session, project_id)
    return [NeedOut.model_validate(r, from_attributes=True) for r in rows]


@router.put("/tasks/{task_id}/needs", status_code=204)
async def set_needs(
    task_id: uuid.UUID, body: NeedsIn, session: SessionDep, request: Request
) -> None:
    try:
        await service.set_needs(deps.database(request), session, task_id, body.item_ids)
    except service.NeedsError as exc:
        raise HTTPException(422, str(exc)) from None

"""How each person arranges a project page (tiles)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api import deps
from app.api.deps import SessionDep
from app.services import layouts as service

router = APIRouter(prefix="/api/v1", tags=["layouts"])

Kind = Literal["tasks", "lists", "notes", "files", "money", "note", "list", "file"]
Width = Literal["narrow", "wide", "full"]


class Tile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    id: uuid.UUID | None = None
    width: Width = "full"

    @model_validator(mode="after")
    def _id_only_for_items(self) -> Tile:
        if (self.kind in service.ITEMS) != (self.id is not None):
            raise ValueError("A single note, list or file needs its id; groups have none.")
        return self


class LayoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tiles: Annotated[list[Tile], Field(max_length=100)]


class LayoutOut(BaseModel):
    tiles: list[Tile]
    source: Literal["mine", "owner", "default"]


def _out(layout: service.Layout) -> LayoutOut:
    return LayoutOut(tiles=[Tile.model_validate(t) for t in layout.tiles], source=layout.source)


@router.get("/projects/{project_id}/layout")
async def get_layout(project_id: uuid.UUID, session: SessionDep, request: Request) -> LayoutOut:
    return _out(await service.get_layout(deps.database(request), session, project_id))


@router.put("/projects/{project_id}/layout")
async def save_layout(
    project_id: uuid.UUID, body: LayoutIn, session: SessionDep, request: Request
) -> LayoutOut:
    tiles = [t.model_dump(mode="json", exclude_none=True) for t in body.tiles]
    return _out(await service.save_layout(deps.database(request), session, project_id, tiles))


@router.delete("/projects/{project_id}/layout")
async def reset_layout(project_id: uuid.UUID, session: SessionDep, request: Request) -> LayoutOut:
    return _out(await service.reset_layout(deps.database(request), session, project_id))

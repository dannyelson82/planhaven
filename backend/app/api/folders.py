"""Folders for the projects list, each person's own (ADR 0022)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.services import folders as service

router = APIRouter(prefix="/api/v1", tags=["folders"])

Name = Annotated[str, Field(min_length=1, max_length=100)]


class FolderOut(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    position: float
    projects: int  # how many of your projects are directly in it
    updated_at: datetime
    version: int


class FolderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    parent_id: uuid.UUID | None = None


class FolderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name | None = None
    parent_id: uuid.UUID | None = None  # null (sent) moves it to the top level
    position: Annotated[float, Field(ge=-1e9, le=1e9)] | None = None


class FileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_id: uuid.UUID | None  # null: in no folder


def _out(row: service.FolderRow, count: int) -> FolderOut:
    return FolderOut(
        id=row.id,
        parent_id=row.parent_id,
        name=row.name,
        position=row.position,
        projects=count,
        updated_at=row.updated_at,
        version=row.version,
    )


@router.get("/folders")
async def list_folders(session: SessionDep, request: Request) -> list[FolderOut]:
    result = await service.list_folders(deps.database(request), session)
    return [_out(f, result.counts.get(f.id, 0)) for f in result.folders]


@router.post("/folders", status_code=201)
async def create_folder(body: FolderIn, session: SessionDep, request: Request) -> FolderOut:
    try:
        row = await service.create_folder(
            deps.database(request), session, name=body.name, parent_id=body.parent_id
        )
    except service.FolderError as exc:
        raise HTTPException(400, str(exc)) from None
    return _out(row, 0)


@router.patch("/folders/{folder_id}")
async def update_folder(
    folder_id: uuid.UUID, body: FolderPatch, session: SessionDep, request: Request
) -> FolderOut:
    sent = body.model_fields_set
    try:
        row = await service.update_folder(
            deps.database(request),
            session,
            folder_id,
            name=body.name,
            parent_id=body.parent_id if "parent_id" in sent else service.UNCHANGED,
            position=body.position,
        )
    except service.FolderError as exc:
        raise HTTPException(400, str(exc)) from None
    counts = (await service.list_folders(deps.database(request), session)).counts
    return _out(row, counts.get(row.id, 0))


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(folder_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_folder(deps.database(request), session, folder_id)


@router.put("/projects/{project_id}/folder", status_code=204)
async def file_project(
    project_id: uuid.UUID, body: FileIn, session: SessionDep, request: Request
) -> None:
    await service.file_project(deps.database(request), session, project_id, body.folder_id)

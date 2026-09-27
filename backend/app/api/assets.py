"""Assets (vehicle, boat, house, ...) and their sharing; linking a project to an asset."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.api.projects import _etag, _version
from app.api.sharing import AddMember, MemberOut, RoleChange
from app.services import assets as service
from app.services import sharing as sharing_service
from app.services.projects import ConflictError
from app.services.sharing import SharingError

router = APIRouter(prefix="/api/v1", tags=["assets"])

Kind = Literal["vehicle", "boat", "house", "property", "equipment", "tool", "other"]


class Detail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Annotated[str, Field(min_length=1, max_length=60)]
    value: Annotated[str, Field(max_length=500)]


class AssetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=200)]
    kind: Kind = "other"
    details: Annotated[list[Detail], Field(max_length=40)] = []
    notes: Annotated[str, Field(max_length=20000)] = ""


class LinkedProjectOut(BaseModel):
    id: uuid.UUID
    title: str
    stage: str
    updated_at: datetime


class AssetOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    details: list[Detail]
    notes: str
    role: str | None
    projects: int
    updated_at: datetime
    version: int
    history: list[LinkedProjectOut] | None = None


class ProjectAssetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: uuid.UUID | None


def _out(a: service.AssetRow, history: list[service.LinkedProject] | None = None) -> AssetOut:
    return AssetOut(
        id=a.id,
        name=a.name,
        kind=a.kind,
        details=[Detail(**d) for d in a.details],
        notes=a.notes,
        role=a.role,
        projects=a.projects,
        updated_at=a.updated_at,
        version=a.version,
        history=None
        if history is None
        else [
            LinkedProjectOut(id=p.id, title=p.title, stage=p.stage, updated_at=p.updated_at)
            for p in history
        ],
    )


@router.get("/assets")
async def list_assets(session: SessionDep, request: Request) -> list[AssetOut]:
    return [_out(a) for a in await service.list_assets(deps.database(request), session)]


@router.post("/assets", status_code=201)
async def create_asset(
    body: AssetIn, session: SessionDep, request: Request, response: Response
) -> AssetOut:
    asset = await service.create_asset(
        deps.database(request),
        session,
        name=body.name,
        kind=body.kind,
        details=[d.model_dump() for d in body.details],
        notes=body.notes,
        ip=deps.client_ip(request),
    )
    _etag(response, asset.version)
    return _out(asset, [])


@router.get("/assets/{asset_id}")
async def get_asset(
    asset_id: uuid.UUID, session: SessionDep, request: Request, response: Response
) -> AssetOut:
    asset, history = await service.get_asset(deps.database(request), session, asset_id)
    _etag(response, asset.version)
    return _out(asset, history)


@router.put("/assets/{asset_id}")
async def update_asset(
    asset_id: uuid.UUID,
    body: AssetIn,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> AssetOut:
    try:
        asset = await service.update_asset(
            deps.database(request),
            session,
            asset_id,
            _version(if_match),
            name=body.name,
            kind=body.kind,
            details=[d.model_dump() for d in body.details],
            notes=body.notes,
        )
    except ConflictError:
        raise HTTPException(409, "Someone else changed this asset. Reload and try again.") from None
    _etag(response, asset.version)
    return _out(asset)


@router.delete("/assets/{asset_id}", status_code=204)
async def delete_asset(asset_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_asset(deps.database(request), session, asset_id, deps.client_ip(request))


@router.put("/projects/{project_id}/asset", status_code=204)
async def link_project(
    project_id: uuid.UUID, body: ProjectAssetIn, session: SessionDep, request: Request
) -> None:
    await service.link_project(deps.database(request), session, project_id, body.asset_id)


@router.get("/assets/{asset_id}/members")
async def list_members(
    asset_id: uuid.UUID, session: SessionDep, request: Request
) -> list[MemberOut]:
    rows = await sharing_service.list_members(deps.database(request), session, asset_id, "asset")
    return [
        MemberOut(user_id=r.user_id, display_name=r.display_name, email=r.email, role=r.role)
        for r in rows
    ]


@router.post("/assets/{asset_id}/members", status_code=201)
async def add_member(
    asset_id: uuid.UUID, body: AddMember, session: SessionDep, request: Request
) -> None:
    try:
        await sharing_service.add_member(
            deps.database(request),
            session,
            asset_id,
            body.user_id,
            body.role,
            deps.client_ip(request),
            "asset",
        )
    except SharingError as exc:
        raise HTTPException(409, str(exc)) from None


@router.patch("/assets/{asset_id}/members/{user_id}", status_code=204)
async def change_role(
    asset_id: uuid.UUID, user_id: uuid.UUID, body: RoleChange, session: SessionDep, request: Request
) -> None:
    try:
        await sharing_service.change_role(
            deps.database(request),
            session,
            asset_id,
            user_id,
            body.role,
            deps.client_ip(request),
            "asset",
        )
    except SharingError as exc:
        raise HTTPException(409, str(exc)) from None


@router.delete("/assets/{asset_id}/members/{user_id}", status_code=204)
async def remove_member(
    asset_id: uuid.UUID, user_id: uuid.UUID, session: SessionDep, request: Request
) -> None:
    try:
        await sharing_service.remove_member(
            deps.database(request), session, asset_id, user_id, deps.client_ip(request), "asset"
        )
    except SharingError as exc:
        raise HTTPException(409, str(exc)) from None

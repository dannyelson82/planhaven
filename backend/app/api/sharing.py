"""Sharing endpoints: household directory and project members."""

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.api import deps
from app.api.deps import SessionDep
from app.services import sharing as service
from app.services.sharing import SharingError

router = APIRouter(prefix="/api/v1")

Role = Literal["owner", "editor", "viewer"]


class Person(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str


class MemberOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    role: str


class AddMember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    role: Role = "editor"


class RoleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role


@router.get("/people")
async def directory(session: SessionDep, request: Request) -> list[Person]:
    rows = await service.directory(deps.database(request), session)
    return [Person(id=r.id, display_name=r.display_name, email=r.email) for r in rows]


@router.get("/projects/{project_id}/members")
async def list_members(
    project_id: uuid.UUID, session: SessionDep, request: Request
) -> list[MemberOut]:
    rows = await service.list_members(deps.database(request), session, project_id)
    return [
        MemberOut(user_id=r.user_id, display_name=r.display_name, email=r.email, role=r.role)
        for r in rows
    ]


@router.post("/projects/{project_id}/members", status_code=201)
async def add_member(
    project_id: uuid.UUID, body: AddMember, session: SessionDep, request: Request
) -> None:
    try:
        await service.add_member(
            deps.database(request),
            session,
            project_id,
            body.user_id,
            body.role,
            deps.client_ip(request),
        )
    except SharingError as exc:
        raise HTTPException(409, str(exc)) from None


@router.patch("/projects/{project_id}/members/{user_id}", status_code=204)
async def change_role(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    body: RoleChange,
    session: SessionDep,
    request: Request,
) -> None:
    try:
        await service.change_role(
            deps.database(request), session, project_id, user_id, body.role, deps.client_ip(request)
        )
    except SharingError as exc:
        raise HTTPException(409, str(exc)) from None


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
async def remove_member(
    project_id: uuid.UUID, user_id: uuid.UUID, session: SessionDep, request: Request
) -> None:
    try:
        await service.remove_member(
            deps.database(request), session, project_id, user_id, deps.client_ip(request)
        )
    except SharingError as exc:
        raise HTTPException(409, str(exc)) from None

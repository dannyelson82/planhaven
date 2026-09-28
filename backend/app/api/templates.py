"""Templates: lists and task sets saved for later projects, and their sharing."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.api.projects import _etag, _version
from app.api.sharing import AddMember, MemberOut, RoleChange
from app.services import sharing as sharing_service
from app.services import templates as service
from app.services.projects import ConflictError
from app.services.sharing import SharingError

router = APIRouter(prefix="/api/v1", tags=["templates"])

Name = Annotated[str, Field(min_length=1, max_length=200)]


class TemplateOut(BaseModel):
    id: uuid.UUID
    kind: Literal["list", "tasks"]
    list_kind: str | None
    name: str
    role: str | None
    item_count: int
    updated_at: datetime
    version: int


class TemplateItemOut(BaseModel):
    id: uuid.UUID
    text: str
    quantity: Decimal | None
    unit: str | None
    price_cents: int | None
    notes: str


class TemplateDetail(TemplateOut):
    items: list[TemplateItemOut]


class SaveAs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name


class Rename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name


class Use(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID


class Used(BaseModel):
    list_id: uuid.UUID | None


def _out(t: service.TemplateRow) -> TemplateOut:
    return TemplateOut.model_validate(t, from_attributes=True)


@router.get("/templates")
async def list_templates(
    session: SessionDep, request: Request, kind: Literal["list", "tasks"] | None = None
) -> list[TemplateOut]:
    return [_out(t) for t in await service.list_templates(deps.database(request), session, kind)]


@router.get("/templates/{template_id}")
async def get_template(
    template_id: uuid.UUID, session: SessionDep, request: Request, response: Response
) -> TemplateDetail:
    template, items = await service.get_template(deps.database(request), session, template_id)
    _etag(response, template.version)
    return TemplateDetail(
        **_out(template).model_dump(),
        items=[TemplateItemOut.model_validate(i, from_attributes=True) for i in items],
    )


def _empty(exc: service.EmptyTemplateError) -> HTTPException:
    return HTTPException(422, str(exc))


@router.post("/lists/{list_id}/template", status_code=201)
async def save_list(
    list_id: uuid.UUID, body: SaveAs, session: SessionDep, request: Request
) -> TemplateOut:
    """Save a list (its items, quantities and estimated prices) as a template."""
    try:
        return _out(
            await service.save_list(
                deps.database(request), session, list_id, body.name, deps.client_ip(request)
            )
        )
    except service.EmptyTemplateError as exc:
        raise _empty(exc) from None


@router.post("/projects/{project_id}/tasks/template", status_code=201)
async def save_tasks(
    project_id: uuid.UUID, body: SaveAs, session: SessionDep, request: Request
) -> TemplateOut:
    """Save a project's open tasks (titles and notes) as a template."""
    try:
        return _out(
            await service.save_tasks(
                deps.database(request), session, project_id, body.name, deps.client_ip(request)
            )
        )
    except service.EmptyTemplateError as exc:
        raise _empty(exc) from None


@router.post("/templates/{template_id}/use")
async def use_template(
    template_id: uuid.UUID, body: Use, session: SessionDep, request: Request
) -> Used:
    """Copy the template into a project: a new list, or its tasks."""
    list_id = await service.apply(
        deps.database(request), session, template_id, body.project_id, deps.client_ip(request)
    )
    return Used(list_id=list_id)


@router.patch("/templates/{template_id}")
async def rename_template(
    template_id: uuid.UUID,
    body: Rename,
    session: SessionDep,
    request: Request,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> TemplateOut:
    try:
        template = await service.rename(
            deps.database(request),
            session,
            template_id,
            _version(if_match),
            body.name,
            deps.client_ip(request),
        )
    except ConflictError:
        raise HTTPException(
            409, "Someone else changed this template. Reload and try again."
        ) from None
    _etag(response, template.version)
    return _out(template)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_template(
        deps.database(request), session, template_id, deps.client_ip(request)
    )


@router.delete("/template-items/{item_id}", status_code=204)
async def delete_template_item(item_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    await service.delete_item(deps.database(request), session, item_id)


# ------------------------------------------------------------------ sharing


@router.get("/templates/{template_id}/members")
async def list_members(
    template_id: uuid.UUID, session: SessionDep, request: Request
) -> list[MemberOut]:
    rows = await sharing_service.list_members(
        deps.database(request), session, template_id, "template"
    )
    return [
        MemberOut(user_id=r.user_id, display_name=r.display_name, email=r.email, role=r.role)
        for r in rows
    ]


@router.post("/templates/{template_id}/members", status_code=201)
async def add_member(
    template_id: uuid.UUID, body: AddMember, session: SessionDep, request: Request
) -> None:
    try:
        await sharing_service.add_member(
            deps.database(request),
            session,
            template_id,
            body.user_id,
            body.role,
            deps.client_ip(request),
            "template",
        )
    except SharingError as exc:
        raise HTTPException(409, str(exc)) from None


@router.patch("/templates/{template_id}/members/{user_id}", status_code=204)
async def change_role(
    template_id: uuid.UUID,
    user_id: uuid.UUID,
    body: RoleChange,
    session: SessionDep,
    request: Request,
) -> None:
    try:
        await sharing_service.change_role(
            deps.database(request),
            session,
            template_id,
            user_id,
            body.role,
            deps.client_ip(request),
            "template",
        )
    except SharingError as exc:
        raise HTTPException(409, str(exc)) from None


@router.delete("/templates/{template_id}/members/{user_id}", status_code=204)
async def remove_member(
    template_id: uuid.UUID, user_id: uuid.UUID, session: SessionDep, request: Request
) -> None:
    try:
        await sharing_service.remove_member(
            deps.database(request),
            session,
            template_id,
            user_id,
            deps.client_ip(request),
            "template",
        )
    except SharingError as exc:
        raise HTTPException(409, str(exc)) from None

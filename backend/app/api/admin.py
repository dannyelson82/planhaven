"""Admin endpoints: users and invites (SECURITY.md §7.1). All require an admin session with a
recent second factor, and answer 404 to everyone else and outside ADMIN_ALLOWED_CIDRS."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.services import admin as admin_service
from app.services import invites as invite_service
from app.services.admin import AdminContext, NotAdminError
from app.services.auth import AuthError, StepUpRequiredError

router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(deps.require_admin_network)])


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Annotated[str | None, Field(default=None, max_length=254)] = None


class InviteCreatedOut(BaseModel):
    id: uuid.UUID
    url: str
    expires_at: datetime


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str | None
    created_at: datetime
    expires_at: datetime
    status: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    is_admin: bool
    disabled: bool
    created_at: datetime
    has_second_factor: bool
    last_seen_at: datetime | None


class FlagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: bool


def _ctx(session: SessionDep, request: Request) -> AdminContext:
    return AdminContext(session, deps.client_ip(request))


Ctx = Annotated[AdminContext, Depends(_ctx)]


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, (NotAdminError, LookupError)):
        return HTTPException(404)
    if isinstance(exc, StepUpRequiredError):
        return HTTPException(403, str(exc))
    return HTTPException(400, str(exc))


@router.get("/users")
async def list_users(ctx: Ctx, request: Request) -> list[UserOut]:
    try:
        users = await admin_service.list_users(deps.database(request), ctx)
    except AuthError as exc:
        raise _error(exc) from None
    return [
        UserOut(
            id=u.id,
            email=u.email,
            display_name=u.display_name,
            is_admin=u.is_admin,
            disabled=u.disabled,
            created_at=u.created_at,
            has_second_factor=u.has_second_factor,
            last_seen_at=u.last_seen_at,
        )
        for u in users
    ]


@router.post("/users/{user_id}/disabled", status_code=204)
async def set_disabled(user_id: uuid.UUID, body: FlagRequest, ctx: Ctx, request: Request) -> None:
    try:
        await admin_service.set_disabled(deps.database(request), ctx, user_id, body.value)
    except (AuthError, LookupError) as exc:
        raise _error(exc) from None


@router.post("/users/{user_id}/admin", status_code=204)
async def set_admin(user_id: uuid.UUID, body: FlagRequest, ctx: Ctx, request: Request) -> None:
    try:
        await admin_service.set_admin(deps.database(request), ctx, user_id, body.value)
    except (AuthError, LookupError) as exc:
        raise _error(exc) from None


@router.post("/users/{user_id}/reset-second-factor", status_code=204)
async def reset_second_factor(user_id: uuid.UUID, ctx: Ctx, request: Request) -> None:
    try:
        await admin_service.reset_second_factor(deps.database(request), ctx, user_id)
    except (AuthError, LookupError) as exc:
        raise _error(exc) from None


@router.post("/invites", status_code=201)
async def create_invite(body: InviteRequest, ctx: Ctx, request: Request) -> InviteCreatedOut:
    try:
        admin_service.require_admin(ctx.session)
        created = await invite_service.create(
            deps.database(request),
            base_url=deps.settings(request).base_url,
            created_by=ctx.session.user.id,
            email=body.email,
            ip=ctx.ip,
        )
    except AuthError as exc:
        raise _error(exc) from None
    return InviteCreatedOut(id=created.id, url=created.url, expires_at=created.expires_at)


@router.get("/invites")
async def list_invites(ctx: Ctx, request: Request) -> list[InviteOut]:
    try:
        rows = await admin_service.list_invites(deps.database(request), ctx)
    except AuthError as exc:
        raise _error(exc) from None
    return [
        InviteOut(
            id=r.id,
            email=r.email,
            created_at=r.created_at,
            expires_at=r.expires_at,
            status=r.status,
        )
        for r in rows
    ]


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke_invite(invite_id: uuid.UUID, ctx: Ctx, request: Request) -> None:
    try:
        revoked = await admin_service.revoke_invite(deps.database(request), ctx, invite_id)
    except AuthError as exc:
        raise _error(exc) from None
    if not revoked:
        raise HTTPException(404)

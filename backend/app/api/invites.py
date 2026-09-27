"""Public invite endpoints. The token travels in request bodies only, never in URLs."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.auth import SessionOut, session_out, set_session_cookie
from app.api.deps import SameOrigin
from app.auth.passwords import MAX_LENGTH, PasswordPolicyError
from app.services import invites as invite_service
from app.services.auth import AuthError

router = APIRouter(prefix="/api/v1/invites")

Token = Annotated[str, Field(min_length=1, max_length=200)]


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: Token


class CheckOut(BaseModel):
    valid: bool
    email: str | None = None


class AcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: Token
    email: Annotated[str, Field(min_length=3, max_length=254)]
    display_name: Annotated[str, Field(min_length=1, max_length=100)]
    password: Annotated[str, Field(min_length=1, max_length=MAX_LENGTH)]


@router.post("/check", dependencies=[SameOrigin])
async def check(body: CheckRequest, request: Request) -> CheckOut:
    email = await invite_service.check(deps.database(request), body.token, deps.client_ip(request))
    if email is None:
        return CheckOut(valid=False)
    return CheckOut(valid=True, email=email or None)


@router.post("/accept", status_code=201, dependencies=[SameOrigin])
async def accept(body: AcceptRequest, request: Request, response: Response) -> SessionOut:
    try:
        new = await invite_service.accept(
            deps.database(request),
            token=body.token,
            email=body.email,
            display_name=body.display_name,
            password=body.password,
            ip=deps.client_ip(request),
            user_agent=deps.user_agent(request),
        )
    except (AuthError, PasswordPolicyError) as exc:
        raise HTTPException(400, str(exc)) from None
    set_session_cookie(request, response, new.token)
    return session_out(request, new)

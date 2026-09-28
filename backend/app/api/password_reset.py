"""Public password reset endpoints (the link an admin made). The token travels in request
bodies only, never in URLs."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SameOrigin
from app.auth.passwords import MAX_LENGTH, PasswordPolicyError
from app.services import password_resets as service
from app.services.auth import AuthError

router = APIRouter(prefix="/api/v1/password-reset")

Token = Annotated[str, Field(min_length=1, max_length=200)]


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: Token


class CheckOut(BaseModel):
    valid: bool


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: Token
    password: Annotated[str, Field(min_length=1, max_length=MAX_LENGTH)]


@router.post("/check", dependencies=[SameOrigin])
async def check(body: CheckRequest, request: Request) -> CheckOut:
    valid = await service.check(deps.database(request), body.token, deps.client_ip(request))
    return CheckOut(valid=valid)


@router.post("", status_code=204, dependencies=[SameOrigin])
async def reset(body: ResetRequest, request: Request) -> None:
    try:
        await service.accept(
            deps.database(request),
            token=body.token,
            password=body.password,
            ip=deps.client_ip(request),
        )
    except (AuthError, PasswordPolicyError) as exc:
        raise HTTPException(400, str(exc)) from None

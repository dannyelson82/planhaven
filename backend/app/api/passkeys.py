"""Passkey endpoints (SECURITY.md §7.1)."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.auth import SessionOut, session_out, set_session_cookie
from app.api.deps import PartialSessionDep, SameOrigin, SessionDep
from app.services import passkeys as passkey_service
from app.services.auth import AuthError, StepUpRequiredError

router = APIRouter(prefix="/api/v1/auth/passkeys")


class OptionsOut(BaseModel):
    challenge_id: uuid.UUID
    options: dict[str, Any]


class CredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: uuid.UUID
    credential: dict[str, Any]


class RegisterRequest(CredentialRequest):
    name: Annotated[str, Field(min_length=1, max_length=100)] = "Passkey"


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class PasskeyOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


def _error(exc: AuthError) -> HTTPException:
    return HTTPException(403 if isinstance(exc, StepUpRequiredError) else 400, str(exc))


def _options(o: passkey_service.Options) -> OptionsOut:
    return OptionsOut(challenge_id=o.challenge_id, options=o.options)


@router.post("/register/options")
async def registration_options(session: PartialSessionDep, request: Request) -> OptionsOut:
    try:
        return _options(
            await passkey_service.registration_options(
                deps.database(request), deps.settings(request), session
            )
        )
    except AuthError as exc:
        raise _error(exc) from None


@router.post("/register")
async def register(
    body: RegisterRequest, session: PartialSessionDep, request: Request
) -> RecoveryCodesOut:
    try:
        codes = await passkey_service.register(
            deps.database(request),
            deps.settings(request),
            session,
            challenge_id=body.challenge_id,
            credential=body.credential,
            name=body.name,
            ip=deps.client_ip(request),
        )
    except AuthError as exc:
        raise _error(exc) from None
    return RecoveryCodesOut(recovery_codes=codes)


@router.post("/verify/options")
async def verification_options(session: PartialSessionDep, request: Request) -> OptionsOut:
    try:
        return _options(
            await passkey_service.verification_options(
                deps.database(request), deps.settings(request), session
            )
        )
    except AuthError as exc:
        raise _error(exc) from None


@router.post("/verify", status_code=204)
async def verify(body: CredentialRequest, session: PartialSessionDep, request: Request) -> None:
    try:
        await passkey_service.verify(
            deps.database(request),
            deps.settings(request),
            session,
            challenge_id=body.challenge_id,
            credential=body.credential,
            ip=deps.client_ip(request),
        )
    except AuthError as exc:
        raise _error(exc) from None


@router.post("/login/options", dependencies=[SameOrigin])
async def login_options(request: Request) -> OptionsOut:
    return _options(
        await passkey_service.login_options(deps.database(request), deps.settings(request))
    )


@router.post("/login", dependencies=[SameOrigin])
async def login(body: CredentialRequest, request: Request, response: Response) -> SessionOut:
    try:
        new = await passkey_service.login(
            deps.database(request),
            deps.settings(request),
            challenge_id=body.challenge_id,
            credential=body.credential,
            ip=deps.client_ip(request),
            user_agent=deps.user_agent(request),
        )
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from None
    set_session_cookie(request, response, new.token)
    return session_out(request, new, mfa_verified=True)


@router.get("")
async def list_passkeys(session: SessionDep, request: Request) -> list[PasskeyOut]:
    items = await passkey_service.list_passkeys(deps.database(request), session)
    return [
        PasskeyOut(id=p.id, name=p.name, created_at=p.created_at, last_used_at=p.last_used_at)
        for p in items
    ]


@router.delete("/{passkey_id}", status_code=204)
async def remove(passkey_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    try:
        removed = await passkey_service.remove(
            deps.database(request), session, passkey_id, deps.client_ip(request)
        )
    except AuthError as exc:
        raise _error(exc) from None
    if not removed:
        raise HTTPException(404)

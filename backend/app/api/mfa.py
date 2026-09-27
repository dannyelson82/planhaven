"""Second-factor endpoints (SECURITY.md §7.1). Most accept a partial (password-only)
session, because they are how a session becomes verified."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import PartialSessionDep, SessionDep
from app.services import mfa as mfa_service
from app.services.auth import AuthError

router = APIRouter(prefix="/api/v1/auth/mfa")

Code = Annotated[str, Field(min_length=1, max_length=40)]


class CodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: Code


class EnrollmentOut(BaseModel):
    secret: str
    otpauth_uri: str


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class RemainingOut(BaseModel):
    recovery_codes_remaining: int


class StatusOut(BaseModel):
    has_totp: bool
    has_passkeys: bool
    recovery_codes_remaining: int
    mfa_verified: bool
    recently_verified: bool


def _error(exc: AuthError) -> HTTPException:
    return HTTPException(400, str(exc))


@router.get("/status")
async def status(session: PartialSessionDep, request: Request) -> StatusOut:
    s = await mfa_service.status(deps.database(request), session)
    return StatusOut(
        has_totp=s.has_totp,
        has_passkeys=s.has_passkeys,
        recovery_codes_remaining=s.recovery_codes_remaining,
        mfa_verified=s.mfa_verified,
        recently_verified=s.recently_verified,
    )


@router.post("/totp/enroll")
async def enroll_totp(session: PartialSessionDep, request: Request) -> EnrollmentOut:
    try:
        e = await mfa_service.start_totp_enrollment(
            deps.database(request), deps.keyring(request), session
        )
    except AuthError as exc:
        raise _error(exc) from None
    return EnrollmentOut(secret=e.secret, otpauth_uri=e.otpauth_uri)


@router.post("/totp/confirm")
async def confirm_totp(
    body: CodeRequest, session: PartialSessionDep, request: Request
) -> RecoveryCodesOut:
    try:
        codes = await mfa_service.confirm_totp_enrollment(
            deps.database(request),
            deps.keyring(request),
            session,
            body.code,
            deps.client_ip(request),
        )
    except AuthError as exc:
        raise _error(exc) from None
    return RecoveryCodesOut(recovery_codes=codes)


@router.post("/totp/verify", status_code=204)
async def verify_totp(body: CodeRequest, session: PartialSessionDep, request: Request) -> None:
    try:
        await mfa_service.verify_totp(
            deps.database(request),
            deps.keyring(request),
            session,
            body.code,
            deps.client_ip(request),
        )
    except AuthError as exc:
        raise _error(exc) from None


@router.post("/recovery/verify")
async def verify_recovery(
    body: CodeRequest, session: PartialSessionDep, request: Request
) -> RemainingOut:
    try:
        remaining = await mfa_service.verify_recovery_code(
            deps.database(request), session, body.code, deps.client_ip(request)
        )
    except AuthError as exc:
        raise _error(exc) from None
    return RemainingOut(recovery_codes_remaining=remaining)


@router.post("/recovery/regenerate")
async def regenerate_recovery(session: SessionDep, request: Request) -> RecoveryCodesOut:
    try:
        codes = await mfa_service.regenerate_recovery_codes(
            deps.database(request), session, deps.client_ip(request)
        )
    except AuthError as exc:
        raise _error(exc) from None
    return RecoveryCodesOut(recovery_codes=codes)

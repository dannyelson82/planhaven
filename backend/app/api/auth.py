"""Setup, sign-in and session endpoints (SECURITY.md §7.1, §7.2)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SameOrigin, SessionDep
from app.auth.passwords import MAX_LENGTH, PasswordPolicyError
from app.services import auth as auth_service
from app.services.auth import AuthError, CurrentSession, NewSession, User

router = APIRouter(prefix="/api/v1")

Password = Annotated[str, Field(min_length=1, max_length=MAX_LENGTH)]
Email = Annotated[str, Field(min_length=3, max_length=254)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class SetupRequest(StrictModel):
    setup_token: Annotated[str, Field(min_length=1, max_length=200)]
    email: Email
    display_name: Annotated[str, Field(min_length=1, max_length=100)]
    password: Password


class LoginRequest(StrictModel):
    email: Annotated[str, Field(min_length=1, max_length=254)]
    password: Password


class ChangePasswordRequest(StrictModel):
    current_password: Password
    new_password: Password


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    is_admin: bool


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str
    mfa_verified: bool


class SetupStatus(BaseModel):
    setup_required: bool


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
    )


def _set_session_cookie(request: Request, response: Response, token: str) -> None:
    s = deps.settings(request)
    response.set_cookie(
        deps.session_cookie_name(s),
        token,
        max_age=int(auth_service.ABSOLUTE_TIMEOUT.total_seconds()),
        path="/",
        secure=s.base_scheme == "https",
        httponly=True,
        samesite="lax",
    )


def _session_out(request: Request, new: NewSession | CurrentSession) -> SessionOut:
    mfa = new.mfa_verified if isinstance(new, CurrentSession) else False
    return SessionOut(
        user=_user_out(new.user),
        csrf_token=request.app.state.session_key.csrf_token(new.token),
        mfa_verified=mfa,
    )


@router.get("/setup")
async def setup_status(request: Request) -> SetupStatus:
    return SetupStatus(setup_required=await auth_service.setup_required(deps.database(request)))


@router.post("/setup", status_code=201, dependencies=[SameOrigin])
async def complete_setup(body: SetupRequest, request: Request, response: Response) -> SessionOut:
    try:
        new = await auth_service.complete_setup(
            deps.database(request),
            setup_token=body.setup_token,
            email=body.email,
            display_name=body.display_name,
            password=body.password,
            ip=deps.client_ip(request),
            user_agent=deps.user_agent(request),
        )
    except (AuthError, PasswordPolicyError) as exc:
        raise HTTPException(400, str(exc)) from None
    _set_session_cookie(request, response, new.token)
    return _session_out(request, new)


@router.post("/auth/login", dependencies=[SameOrigin])
async def login(body: LoginRequest, request: Request, response: Response) -> SessionOut:
    db = deps.database(request)
    # Any session this browser already had is ended: a new session ID on every sign-in.
    if old := await deps.optional_session(request):
        await auth_service.logout(db, old, deps.client_ip(request))
    try:
        new = await auth_service.login(
            db,
            email=body.email,
            password=body.password,
            ip=deps.client_ip(request),
            user_agent=deps.user_agent(request),
        )
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from None
    _set_session_cookie(request, response, new.token)
    return _session_out(request, new)


@router.post("/auth/logout", status_code=204)
async def logout(session: SessionDep, request: Request, response: Response) -> None:
    await auth_service.logout(deps.database(request), session, deps.client_ip(request))
    response.delete_cookie(
        deps.session_cookie_name(deps.settings(request)),
        path="/",
        secure=deps.settings(request).base_scheme == "https",
        httponly=True,
        samesite="lax",
    )


@router.get("/auth/session")
async def current_session(session: SessionDep, request: Request) -> SessionOut:
    return _session_out(request, session)


@router.post("/auth/password", status_code=204)
async def change_password(
    body: ChangePasswordRequest, session: SessionDep, request: Request
) -> None:
    try:
        await auth_service.change_password(
            deps.database(request),
            session,
            current_password=body.current_password,
            new_password=body.new_password,
            ip=deps.client_ip(request),
        )
    except (AuthError, PasswordPolicyError) as exc:
        raise HTTPException(400, str(exc)) from None

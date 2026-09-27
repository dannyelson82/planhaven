"""Request dependencies shared by routers: settings, database, client address, the current
session, and CSRF protection (SECURITY.md §7.2)."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from app.core.config import Settings
from app.services import auth as auth_service
from app.services.auth import CurrentSession

CSRF_HEADER = "x-csrf-token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def settings(request: Request) -> Settings:
    value: Settings = request.app.state.settings
    return value


def database(request: Request) -> Any:
    return request.app.state.db


def client_ip(request: Request) -> str | None:
    # Already resolved from trusted proxies by ProxyHeadersMiddleware; "testclient" etc. are
    # not addresses and are dropped.
    host = request.client.host if request.client else None
    if host is None:
        return None
    return host if any(c in host for c in ".:") else None


def user_agent(request: Request) -> str | None:
    value = request.headers.get("user-agent")
    return value[:200] if value else None


def session_cookie_name(s: Settings) -> str:
    # __Host- requires Secure, which only works over https (private http mode drops it).
    return "__Host-planhaven_session" if s.base_scheme == "https" else "planhaven_session"


def require_same_origin(request: Request) -> None:
    """Unsafe requests must come from our own pages: the browser-set Origin header must equal
    BASE_URL. Stops login CSRF and cross-site form posts even before a session exists."""
    if request.method not in UNSAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin != settings(request).base_origin:
        raise HTTPException(403, "Cross-origin request refused.")


async def optional_session(request: Request) -> CurrentSession | None:
    token = request.cookies.get(session_cookie_name(settings(request)), "")
    return await auth_service.authenticate(database(request), token)


async def require_session(
    request: Request, session: Annotated[CurrentSession | None, Depends(optional_session)]
) -> CurrentSession:
    """A signed-in session. Unsafe methods also need the session's CSRF token."""
    if session is None:
        raise HTTPException(401, "Sign in to continue.")
    if request.method in UNSAFE_METHODS:
        require_same_origin(request)
        presented = request.headers.get(CSRF_HEADER, "")
        if not request.app.state.session_key.csrf_valid(session.token, presented):
            raise HTTPException(403, "Missing or invalid CSRF token.")
    return session


async def require_verified_session(
    session: Annotated[CurrentSession, Depends(require_session)],
) -> CurrentSession:
    """A session that has completed the second factor. Everything except sign-in, the second
    factor itself and sign-out requires this (SECURITY.md §7.1)."""
    if not session.mfa_verified:
        raise HTTPException(403, "Second factor required.")
    return session


def keyring(request: Request) -> Any:
    return request.app.state.keyring


# Password only (partial) sessions: use solely for the second-factor and sign-out routes.
PartialSessionDep = Annotated[CurrentSession, Depends(require_session)]
SessionDep = Annotated[CurrentSession, Depends(require_verified_session)]
SameOrigin = Depends(require_same_origin)

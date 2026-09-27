"""Request dependencies shared by routers: settings, database, client address, the current
session, and CSRF protection (SECURITY.md §7.2)."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from app import authz
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


def blobs(request: Request) -> Any:
    return request.app.state.blobs


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
    authz.require(session.principal, authz.Action.USE_APP)
    return session


def keyring(request: Request) -> Any:
    return request.app.state.keyring


# Password only (partial) sessions: use solely for the second-factor and sign-out routes.
PartialSessionDep = Annotated[CurrentSession, Depends(require_session)]
SessionDep = Annotated[CurrentSession, Depends(require_verified_session)]
SameOrigin = Depends(require_same_origin)


def require_admin_network(request: Request) -> None:
    """With ADMIN_ALLOWED_CIDRS set, admin routes answer 404 from anywhere else, so the admin
    area isn't even discoverable from the internet (SECURITY.md §7.11)."""
    import ipaddress

    allowed = settings(request).admin_allowed_cidrs
    if not allowed:
        return
    ip = client_ip(request)
    try:
        address = ipaddress.ip_address(ip) if ip else None
    except ValueError:
        address = None
    if address is None or not any(address in net for net in allowed):
        raise HTTPException(404)


async def require_admin(
    session: Annotated[CurrentSession, Depends(require_session)],
) -> CurrentSession:
    """Admin with a recent second factor. Runs before request bodies are validated, so a
    non-admin gets the same 404 for every admin route."""
    authz.require(session.principal, authz.Action.ADMIN)
    return session


async def websocket_session(websocket: Any) -> CurrentSession | None:
    """Authenticate a WebSocket handshake (SECURITY.md §7.15): the browser-set Origin must be
    ours (no cross-site WebSocket hijacking), and the session cookie must belong to a session
    that has completed its second factor."""
    settings_: Settings = websocket.app.state.settings
    if websocket.headers.get("origin") != settings_.base_origin:
        return None
    token = websocket.cookies.get(session_cookie_name(settings_), "")
    session = await auth_service.authenticate(websocket.app.state.db, token)
    if session is None or not authz.allowed(session.principal, authz.Action.USE_APP):
        return None
    return session

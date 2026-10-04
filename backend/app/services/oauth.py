"""OAuth 2.1 authorization server for AI apps (ADR 0007, ADR 0019, A§12.2; RFC 6749, 7591,
7636, 7009, 8414, 9700).

- Public clients only (no client secrets: AI apps register themselves); PKCE S256 required.
- Redirect URIs match exactly one the client registered: https, or http on the loopback
  address for apps on this computer. An unknown client or redirect never redirects.
- A code works once, for two minutes, for the redirect URI and PKCE verifier it was made with;
  using it twice revokes what it gave.
- Access tokens last an hour and are only for /mcp. Refresh tokens last 30 days and are
  rotated on each use; a used one coming back (a replay) revokes the whole family.
- A registered client can do nothing until a person approves it on the consent screen, after a
  fresh second factor, choosing read or write and, for writes, approve-first or apply-with-undo.
"""

import base64
import hashlib
import hmac
import uuid
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from sqlalchemy.ext.asyncio import AsyncConnection

from app import authz
from app.auth import tokens
from app.core import security_log
from app.db import admin as admin_store
from app.db import auth as audit
from app.db import oauth as store
from app.db.database import Database
from app.services import limits
from app.services.auth import CurrentSession

ACCESS_SECONDS = 3600
REFRESH_SECONDS = 30 * 24 * 3600
SCOPES = {"projects:read": "read", "projects:write": "write"}
MODES = ("approve", "apply")
ACCESS_PREFIX = "phv_oat_"
REFRESH_PREFIX = "phv_ort_"
CODE_PREFIX = "phv_occ_"  # authorization codes (never logged: in the URL query, redacted)


class OAuthError(Exception):
    """An error the token or registration endpoint returns as JSON (RFC 6749 §5.2)."""

    def __init__(self, error: str, description: str, status: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status = status


class AuthorizeError(Exception):
    """A bad authorization request that must not redirect (unknown client or redirect)."""


class RedirectError(Exception):
    """A bad authorization request reported back to the client's redirect URI."""

    def __init__(self, redirect_uri: str, error: str, description: str, state: str | None) -> None:
        super().__init__(description)
        self.url = _with_query(
            redirect_uri, {"error": error, "error_description": description, "state": state}
        )


def _with_query(uri: str, params: dict[str, str | None]) -> str:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    return f"{uri}{'&' if urlsplit(uri).query else '?'}{query}"


def redirect_allowed(uri: str) -> bool:
    """https anywhere, or http on this computer's loopback (desktop apps); no fragment, no
    user info, at most 500 characters."""
    if len(uri) > 500 or "#" in uri:
        return False
    try:
        parts = urlsplit(uri)
        parts.port  # noqa: B018 (raises ValueError on a bad port)
    except ValueError:
        return False
    if parts.username or parts.password or not parts.hostname:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")


def pkce_ok(verifier: str, challenge: str) -> bool:
    if not 43 <= len(verifier) <= 128:
        return False
    digest = hashlib.sha256(verifier.encode("ascii", "ignore")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(expected, challenge)


def _scope_of(raw: str | None) -> str:
    """The most a client asks for: write if it asks for projects:write (or nothing, so the
    person chooses), read for projects:read only. Unknown scopes are an error."""
    if not raw:
        return "write"
    asked = set(raw.split())
    if not asked or asked - set(SCOPES):
        raise ValueError("unknown scope")
    return "write" if "projects:write" in asked else "read"


def scope_text(scope: str) -> str:
    return "projects:read projects:write" if scope == "write" else "projects:read"


# ---------------------------------------------------------------- registration (RFC 7591)


async def register(
    db: Database, *, client_name: str, redirect_uris: list[str], ip: str | None
) -> store.ClientRow:
    await limits.check(
        db, [(limits.OAUTH_REGISTER_IP, limits.key(limits.OAUTH_REGISTER_IP, ip))], ip=ip
    )
    name = " ".join(client_name.split())[:100] or "AI app"
    if not redirect_uris or len(redirect_uris) > 5:
        raise OAuthError("invalid_redirect_uri", "Give one to five redirect URIs.")
    for uri in redirect_uris:
        if not redirect_allowed(uri):
            raise OAuthError("invalid_redirect_uri", "Redirect URIs must be https (or loopback).")
    async with db.system_transaction() as conn:
        row = await store.create_client(conn, "phc_" + tokens.new_token()[:32], name, redirect_uris)
        await audit.record_audit(
            conn,
            action="oauth.client_registered",
            actor_user_id=None,
            ip=ip,
            resource_type="oauth_client",
            resource_id=row.id,
        )
    return row


# ---------------------------------------------------------------- authorization


async def start(
    db: Database,
    *,
    response_type: str | None,
    client_id: str | None,
    redirect_uri: str | None,
    code_challenge: str | None,
    code_challenge_method: str | None,
    scope: str | None,
    state: str | None,
    resource: str | None,
    mcp_url: str,
) -> uuid.UUID:
    """Check an authorization request and keep it for the consent screen."""
    async with db.system_transaction() as conn:
        client = await store.client(conn, client_id or "")
    if client is None:
        raise AuthorizeError("This app isn't registered with PlanHaven.")
    if redirect_uri is None and len(client.redirect_uris) == 1:
        redirect_uri = client.redirect_uris[0]
    if redirect_uri not in client.redirect_uris:
        raise AuthorizeError("This app asked to return to an address it didn't register.")
    state = state[:500] if state else None
    if response_type != "code":
        raise RedirectError(redirect_uri, "unsupported_response_type", "Only code.", state)
    if code_challenge_method != "S256" or not code_challenge or len(code_challenge) != 43:
        raise RedirectError(redirect_uri, "invalid_request", "PKCE S256 is required.", state)
    if resource and resource.rstrip("/") != mcp_url.rstrip("/"):
        raise RedirectError(redirect_uri, "invalid_target", "Unknown resource.", state)
    try:
        asked = _scope_of(scope)
    except ValueError:
        raise RedirectError(redirect_uri, "invalid_scope", "Unknown scope.", state) from None
    async with db.system_transaction() as conn:
        return await store.create_request(
            conn,
            client_id=client.id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=asked,
            state=state,
        )


@dataclass(frozen=True, slots=True)
class Consent:
    client_name: str
    redirect_host: str
    scope: str  # the most it may be given: read or write


async def consent(db: Database, session: CurrentSession, request_id: uuid.UUID) -> Consent:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.system_transaction() as conn:
        req = await store.request(conn, request_id)
        client = await store.client_by_id(conn, req.client_id) if req else None
    if req is None or client is None:
        raise authz.NotFoundError("This request has expired. Start again from the AI app.")
    return Consent(client.client_name, urlsplit(req.redirect_uri).hostname or "", req.scope)


async def approve(
    db: Database,
    session: CurrentSession,
    request_id: uuid.UUID,
    *,
    scope: str,
    write_mode: str,
    issuer: str,
    ip: str | None,
) -> str:
    """The person approves: a connection (grant) and a single-use code. Returns where to send
    the browser back to (the app's redirect URI with the code)."""
    authz.require(session.principal, authz.Action.AI_CONNECT)
    if scope not in ("read", "write") or write_mode not in MODES:
        raise authz.ForbiddenError("Unknown choice.")
    async with db.system_transaction() as conn:
        req = await store.request(conn, request_id)
        if req is None:
            raise authz.NotFoundError("This request has expired. Start again from the AI app.")
        if req.scope == "read" and scope == "write":
            scope = "read"  # never more than the app asked for
        grant_id = await store.create_grant(
            conn,
            user_id=session.user.id,
            client_id=req.client_id,
            scope=scope,
            write_mode=write_mode,
        )
        code = tokens.new_token(CODE_PREFIX)
        await store.create_code(
            conn,
            code_hash=tokens.token_hash(code),
            grant_id=grant_id,
            redirect_uri=req.redirect_uri,
            code_challenge=req.code_challenge,
        )
        await store.delete_request(conn, request_id)
        await audit.record_audit(
            conn,
            action="oauth.connected",
            actor_user_id=session.user.id,
            ip=ip,
            resource_type="oauth_grant",
            resource_id=grant_id,
        )
        await admin_store.notify(
            conn, session.user.id, "security_change", {"change": "ai_app_connected", "ip": ip}
        )
    return _with_query(req.redirect_uri, {"code": code, "state": req.state, "iss": issuer})


async def deny(db: Database, session: CurrentSession, request_id: uuid.UUID) -> str:
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.system_transaction() as conn:
        req = await store.request(conn, request_id)
        if req is None:
            raise authz.NotFoundError("This request has expired.")
        await store.delete_request(conn, request_id)
    return _with_query(
        req.redirect_uri,
        {"error": "access_denied", "error_description": "Not approved.", "state": req.state},
    )


# ---------------------------------------------------------------- tokens


@dataclass(frozen=True, slots=True)
class Tokens:
    access_token: str
    refresh_token: str
    scope: str


async def _issue(
    conn: AsyncConnection, grant_id: uuid.UUID, family_id: uuid.UUID
) -> tuple[str, str]:
    access = tokens.new_token(ACCESS_PREFIX)
    refresh = tokens.new_token(REFRESH_PREFIX)
    await store.add_token(
        conn,
        grant_id=grant_id,
        family_id=family_id,
        kind="access",
        token_hash=tokens.token_hash(access),
        lifetime_seconds=ACCESS_SECONDS,
    )
    await store.add_token(
        conn,
        grant_id=grant_id,
        family_id=family_id,
        kind="refresh",
        token_hash=tokens.token_hash(refresh),
        lifetime_seconds=REFRESH_SECONDS,
    )
    return access, refresh


def _failed(ip: str | None, reason: str) -> OAuthError:
    security_log.event("oauth_failed", ip=ip, reason=reason)
    return OAuthError("invalid_grant", "The code or token isn't valid.")


async def exchange_code(
    db: Database,
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    code_verifier: str,
    ip: str | None,
) -> Tokens:
    await limits.check(db, [(limits.OAUTH_TOKEN_IP, limits.key(limits.OAUTH_TOKEN_IP, ip))], ip=ip)
    # Failures are raised after the transaction commits: the code stays spent, and a reused
    # code's revocations stick.
    problem = None
    async with db.system_transaction() as conn:
        row = await store.take_code(conn, tokens.token_hash(code))
        grant = await store.grant(conn, row.grant_id) if row else None
        client = await store.client(conn, client_id)
        if row is None:
            problem = "unknown_code"
        elif row.used:
            # A code used twice: revoke what it gave (RFC 6749 §4.1.2).
            await store.revoke_grant(conn, row.grant_id)
            await store.revoke_grant_tokens(conn, row.grant_id)
            problem = "code_reused"
        elif (
            row.expired
            or grant is None
            or grant.revoked_at is not None
            or client is None
            or client.id != grant.client_id
            or redirect_uri != row.redirect_uri
        ):
            problem = "code_mismatch"
        elif not pkce_ok(code_verifier, row.code_challenge):
            problem = "pkce"
        else:
            access, refresh = await _issue(conn, grant.id, uuid.uuid7())
    if problem is not None or grant is None:
        raise _failed(ip, problem or "code_mismatch")
    return Tokens(access, refresh, scope_text(grant.scope))


async def refresh(db: Database, *, refresh_token: str, client_id: str, ip: str | None) -> Tokens:
    await limits.check(db, [(limits.OAUTH_TOKEN_IP, limits.key(limits.OAUTH_TOKEN_IP, ip))], ip=ip)
    problem = None  # raised after commit, so a reuse's revocation sticks
    async with db.system_transaction() as conn:
        row = await store.token(conn, tokens.token_hash(refresh_token))
        grant = await store.grant(conn, row.grant_id) if row else None
        client = await store.client(conn, client_id)
        if row is None or row.kind != "refresh":
            problem = "unknown_refresh"
        elif row.revoked or row.expired or grant is None or client is None:
            problem = "refresh_invalid"
        elif client.id != grant.client_id:
            problem = "refresh_client"
        elif row.used or not await store.use_refresh(conn, row.id):
            # A rotated refresh token came back: someone has a copy. End the whole family.
            await store.revoke_family(conn, row.family_id)
            problem = "refresh_reused"
        else:
            access, new_refresh = await _issue(conn, grant.id, row.family_id)
    if problem is not None or grant is None:
        raise _failed(ip, problem or "refresh_invalid")
    return Tokens(access, new_refresh, scope_text(grant.scope))


async def revoke(db: Database, *, token: str) -> None:
    """RFC 7009: always succeeds from the client's point of view."""
    async with db.system_transaction() as conn:
        row = await store.token(conn, tokens.token_hash(token))
        if row is not None:
            await store.revoke_family(conn, row.family_id)


@dataclass(frozen=True, slots=True)
class Connection:
    """Who an access token acts for, and what it may do."""

    principal: authz.Principal
    grant: store.GrantRow


async def authenticate(db: Database, token: str) -> Connection | None:
    if not token.startswith(ACCESS_PREFIX) or len(token) > 120:
        return None
    async with db.system_transaction() as conn:
        row = await store.token(conn, tokens.token_hash(token))
        if row is None or row.kind != "access" or row.expired or row.revoked:
            return None
        grant = await store.grant(conn, row.grant_id)
        if grant is None:
            return None
        await store.grant_used(conn, grant.id)
    kind = "mcp_write" if grant.scope == "write" else "mcp_read"
    return Connection(authz.Principal(grant.user_id, False, True, None, kind=kind), grant)


# ---------------------------------------------------------------- the person's connections


async def connections(db: Database, session: CurrentSession) -> list[store.GrantRow]:
    """The person's own connections (read in system context because app names live with the
    system-only client records; filtered to this person)."""
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.system_transaction() as conn:
        return await store.grants_of(conn, session.user.id)


async def _own_grant(db: Database, session: CurrentSession, grant_id: uuid.UUID) -> store.GrantRow:
    async with db.system_transaction() as conn:
        grant = await store.grant(conn, grant_id)
    if grant is None or grant.user_id != session.user.id or grant.revoked_at is not None:
        raise authz.NotFoundError("Not found.")
    return grant


async def change(
    db: Database, session: CurrentSession, grant_id: uuid.UUID, *, scope: str, write_mode: str
) -> None:
    """Narrowing (to read, or to approve-first) needs nothing more; widening needs a fresh
    second factor, like connecting."""
    if scope not in ("read", "write") or write_mode not in MODES:
        raise authz.ForbiddenError("Unknown choice.")
    before = await _own_grant(db, session, grant_id)
    async with db.user_transaction(session.user.id) as conn:
        widening = (scope == "write" and before.scope == "read") or (
            write_mode == "apply" and before.write_mode == "approve"
        )
        authz.require(
            session.principal, authz.Action.AI_CONNECT if widening else authz.Action.USE_APP
        )
        await store.update_grant(conn, grant_id, scope=scope, write_mode=write_mode)


async def disconnect(
    db: Database, session: CurrentSession, grant_id: uuid.UUID, ip: str | None
) -> None:
    authz.require(session.principal, authz.Action.USE_APP)
    await _own_grant(db, session, grant_id)
    async with db.user_transaction(session.user.id) as conn:
        await store.revoke_grant(conn, grant_id)
        await audit.record_audit(
            conn,
            action="oauth.disconnected",
            actor_user_id=session.user.id,
            ip=ip,
            resource_type="oauth_grant",
            resource_id=grant_id,
        )
    async with db.system_transaction() as conn:
        await store.revoke_grant_tokens(conn, grant_id)

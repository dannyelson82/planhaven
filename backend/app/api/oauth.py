"""OAuth 2.1 for AI apps (ADR 0007, A§12.2): discovery metadata, registration, the
authorization request (handed to the consent screen), the token endpoint and revocation; and
the consent screen's own API (signed-in session).

The registration, token and revocation endpoints are called by AI apps' servers: no cookies
are read there, so they are public by design (no CSRF exposure) and rate limited per address.
"""

import json
import uuid
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api import deps
from app.api.deps import SessionDep
from app.services import oauth as service

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _base(request: Request) -> str:
    return str(deps.settings(request).base_url).rstrip("/")


def _oauth_error(exc: service.OAuthError) -> JSONResponse:
    return JSONResponse(
        {"error": exc.error, "error_description": exc.description},
        status_code=exc.status,
        headers=NO_STORE,
    )


# ---------------------------------------------------------------- discovery (RFC 8414, 9728)


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def metadata(request: Request) -> JSONResponse:
    base = _base(request)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "revocation_endpoint": f"{base}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "revocation_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": list(service.SCOPES),
            "authorization_response_iss_parameter_supported": True,
        }
    )


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
@router.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
async def resource_metadata(request: Request) -> JSONResponse:
    base = _base(request)
    return JSONResponse(
        {
            "resource": f"{base}/mcp",
            "authorization_servers": [base],
            "scopes_supported": list(service.SCOPES),
            "bearer_methods_supported": ["header"],
            "resource_name": "PlanHaven",
        }
    )


# ---------------------------------------------------------------- registration (RFC 7591)


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="ignore")  # clients send many optional fields
    client_name: Annotated[str, Field(max_length=200)] = "AI app"
    redirect_uris: Annotated[list[Annotated[str, Field(max_length=500)]], Field(max_length=5)]
    token_endpoint_auth_method: str = "none"  # noqa: S105  # nosec B105: an OAuth method name
    grant_types: Annotated[list[Annotated[str, Field(max_length=40)]], Field(max_length=5)] = [
        "authorization_code",
        "refresh_token",
    ]
    response_types: Annotated[list[Annotated[str, Field(max_length=40)]], Field(max_length=5)] = [
        "code"
    ]


@router.post("/oauth/register", status_code=201, include_in_schema=False)
async def register(body: RegisterIn, request: Request) -> JSONResponse:
    if body.token_endpoint_auth_method != "none":  # noqa: S105  # nosec B105
        return _oauth_error(
            service.OAuthError("invalid_client_metadata", "Only public clients (PKCE).")
        )
    if not set(body.grant_types) <= {
        "authorization_code",
        "refresh_token",
    } or body.response_types != ["code"]:
        return _oauth_error(service.OAuthError("invalid_client_metadata", "Only the code flow."))
    try:
        client = await service.register(
            deps.database(request),
            client_name=body.client_name,
            redirect_uris=body.redirect_uris,
            ip=deps.client_ip(request),
        )
    except service.OAuthError as exc:
        return _oauth_error(exc)
    return JSONResponse(
        {
            "client_id": client.client_id,
            "client_name": client.client_name,
            "redirect_uris": client.redirect_uris,
            "token_endpoint_auth_method": "none",  # nosec B105: an OAuth method name
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "client_id_issued_at": int(client.created_at.timestamp()),
        },
        status_code=201,
        headers=NO_STORE,
    )


# ---------------------------------------------------------------- authorization


@router.get("/oauth/authorize", include_in_schema=False)
async def authorize(request: Request) -> RedirectResponse:
    """Check the request, keep it, and send the browser to the consent screen."""
    q = request.query_params
    try:
        request_id = await service.start(
            deps.database(request),
            response_type=q.get("response_type"),
            client_id=q.get("client_id"),
            redirect_uri=q.get("redirect_uri"),
            code_challenge=q.get("code_challenge"),
            code_challenge_method=q.get("code_challenge_method"),
            scope=q.get("scope"),
            state=q.get("state"),
            resource=q.get("resource"),
            mcp_url=f"{_base(request)}/mcp",
        )
    except service.AuthorizeError:
        return RedirectResponse("/connect?problem=unknown", status_code=303)
    except service.RedirectError as exc:
        return RedirectResponse(exc.url, status_code=303)
    return RedirectResponse(f"/connect?{urlencode({'request': str(request_id)})}", status_code=303)


async def _form(request: Request) -> dict[str, str]:
    """application/x-www-form-urlencoded (the standard), or JSON from lenient clients."""
    raw = (await request.body()).decode("utf-8", "replace")
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            data: Any = json.loads(raw)
        except ValueError:
            return {}
        return {k: str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    try:
        fields = parse_qs(raw, max_num_fields=20)
    except ValueError:  # too many fields
        return {}
    return {k: v[0] for k, v in fields.items()}


@router.post("/oauth/token", include_in_schema=False)
async def token(request: Request) -> JSONResponse:
    form = await _form(request)
    grant_type = form.get("grant_type")
    db = deps.database(request)
    ip = deps.client_ip(request)
    try:
        if grant_type == "authorization_code":
            result = await service.exchange_code(
                db,
                code=form.get("code", ""),
                redirect_uri=form.get("redirect_uri", ""),
                client_id=form.get("client_id", ""),
                code_verifier=form.get("code_verifier", ""),
                ip=ip,
            )
        elif grant_type == "refresh_token":
            result = await service.refresh(
                db,
                refresh_token=form.get("refresh_token", ""),
                client_id=form.get("client_id", ""),
                ip=ip,
            )
        else:
            raise service.OAuthError("unsupported_grant_type", "Unsupported grant type.")
    except service.OAuthError as exc:
        return _oauth_error(exc)
    return JSONResponse(
        {
            "access_token": result.access_token,
            "token_type": "Bearer",  # nosec B105: the token type
            "expires_in": service.ACCESS_SECONDS,
            "refresh_token": result.refresh_token,
            "scope": result.scope,
        },
        headers=NO_STORE,
    )


@router.post("/oauth/revoke", include_in_schema=False)
async def revoke(request: Request) -> JSONResponse:
    form = await _form(request)
    await service.revoke(deps.database(request), token=form.get("token", "")[:200])
    return JSONResponse({}, headers=NO_STORE)


# ---------------------------------------------------------------- the consent screen (session)


class ConsentOut(BaseModel):
    client_name: str
    redirect_host: str
    scope: str


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["read", "write"]
    write_mode: Literal["approve", "apply"] = "approve"


class RedirectOut(BaseModel):
    redirect: str


@router.get("/api/v1/oauth/requests/{request_id}")
async def consent(request_id: uuid.UUID, session: SessionDep, request: Request) -> ConsentOut:
    c = await service.consent(deps.database(request), session, request_id)
    return ConsentOut(client_name=c.client_name, redirect_host=c.redirect_host, scope=c.scope)


@router.post("/api/v1/oauth/requests/{request_id}/approve")
async def approve(
    request_id: uuid.UUID, body: ApproveIn, session: SessionDep, request: Request
) -> RedirectOut:
    url = await service.approve(
        deps.database(request),
        session,
        request_id,
        scope=body.scope,
        write_mode=body.write_mode,
        issuer=_base(request),
        ip=deps.client_ip(request),
    )
    return RedirectOut(redirect=url)


@router.post("/api/v1/oauth/requests/{request_id}/deny")
async def deny(request_id: uuid.UUID, session: SessionDep, request: Request) -> RedirectOut:
    url = await service.deny(deps.database(request), session, request_id)
    return RedirectOut(redirect=url)

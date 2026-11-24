"""The iPhone app's sign-in (ADR 0021): a built-in OAuth client, tokens for /api/v1 only,
web-only account security, signed-in apps, and live-update tickets."""

import asyncio
import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app.db import oauth as oauth_store
from app.db.database import Database
from tests.db import team as setup
from tests.db.conftest import _settings
from tests.db.team import ORIGIN, PASSWORD, U

pytestmark = pytest.mark.db

team = setup.team

type Team = tuple[U, U, U, str, str]
CLIENT = "phc_planhaven_ios"
REDIRECT = "app.planhaven.ios:/oauth/callback"


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _start(u: U, challenge: str, device: str = "Ann's iPhone", **extra: str) -> str:
    u.client.cookies.clear()
    r = u.client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": CLIENT,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "s1",
            "resource": f"{ORIGIN}/api/v1",
            "device_name": device,
            **extra,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    location: str = r.headers["location"]
    assert location.startswith("/connect?request="), location
    return location.split("=", 1)[1]


def _token(u: U, **form: str) -> Any:
    u.client.cookies.clear()
    return u.client.post("/oauth/token", data={"client_id": CLIENT, **form})


def _sign_in(u: U, device: str = "Ann's iPhone") -> dict[str, Any]:
    verifier, challenge = _pkce()
    request_id = _start(u, challenge, device)
    u._cookie()
    r = u.client.post(f"/api/v1/oauth/requests/{request_id}/approve", headers=u.h, json={})
    assert r.status_code == 200, r.text
    redirect = r.json()["redirect"]
    assert redirect.startswith(REDIRECT + "?")
    q = parse_qs(urlsplit(redirect).query)
    assert q["state"] == ["s1"]
    assert q["iss"] == [ORIGIN]
    t = _token(
        u,
        grant_type="authorization_code",
        code=q["code"][0],
        redirect_uri=REDIRECT,
        code_verifier=verifier,
    )
    assert t.status_code == 200, t.text
    body: dict[str, Any] = t.json()
    return body


def _api(u: U, method: str, path: str, token: str, **kw: Any) -> Any:
    u.client.cookies.clear()
    headers = {"authorization": f"Bearer {token}", **kw.pop("headers", {})}
    return u.client.request(method, path, headers=headers, **kw)


def _sql(statement: str, **params: Any) -> None:
    async def run() -> None:
        db = Database(_settings())
        async with db.system_transaction() as conn:
            await conn.execute(text(statement), params)
        await db.dispose()

    asyncio.run(run())


def test_sign_in_and_use_the_api_without_csrf(team: Team) -> None:
    owner, _, _, pid, _ = team
    _, challenge = _pkce()
    request_id = _start(owner, challenge)
    owner._cookie()
    consent = owner.client.get(f"/api/v1/oauth/requests/{request_id}").json()
    assert consent["scope"] == "app"
    assert consent["client_name"] == "PlanHaven for iPhone"
    assert consent["device_name"] == "Ann's iPhone"

    tokens = _sign_in(owner)
    assert tokens["access_token"].startswith("phv_aat_")
    assert tokens["refresh_token"].startswith("phv_art_")
    assert tokens["scope"] == "app"
    access = tokens["access_token"]
    # No cookie, no CSRF token: reads and writes work.
    assert _api(owner, "GET", "/api/v1/projects", access).status_code == 200
    r = _api(owner, "POST", f"/api/v1/projects/{pid}/tasks", access, json={"title": "Paint"})
    assert r.status_code == 201, r.text
    # A cookie and a token together are refused.
    owner._cookie()
    both = owner.client.get("/api/v1/projects", headers={"authorization": f"Bearer {access}"})
    assert both.status_code == 400
    # A token that doesn't exist.
    bad = _api(owner, "GET", "/api/v1/projects", "phv_aat_" + "x" * 43)
    assert bad.status_code == 401
    assert "invalid_token" in bad.headers["www-authenticate"]


def test_signing_in_needs_a_fresh_second_factor(team: Team) -> None:
    owner = team[0]
    _sql("UPDATE sessions SET reauth_at = now() - interval '6 minutes'")
    _, challenge = _pkce()
    request_id = _start(owner, challenge)
    owner._cookie()
    r = owner.client.post(f"/api/v1/oauth/requests/{request_id}/approve", headers=owner.h, json={})
    assert r.status_code == 403


def test_tokens_only_work_where_they_belong(team: Team) -> None:
    owner = team[0]
    access = _sign_in(owner)["access_token"]
    # The app's token isn't an AI app's.
    owner.client.cookies.clear()
    mcp = owner.client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"authorization": f"Bearer {access}"},
    )
    assert mcp.status_code == 401
    # The app's redirect scheme can't be registered by anyone else, or used by another client.
    owner.client.cookies.clear()
    reg = owner.client.post("/oauth/register", json={"redirect_uris": [REDIRECT]})
    assert reg.status_code == 400
    # An AI app can't ask for the REST API.
    reg = owner.client.post(
        "/oauth/register", json={"redirect_uris": ["https://ai.example.com/cb"]}
    )
    client_id = reg.json()["client_id"]
    _, challenge = _pkce()
    r = owner.client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://ai.example.com/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": f"{ORIGIN}/api/v1",
        },
        follow_redirects=False,
    )
    assert "error=invalid_target" in r.headers["location"]
    # And the app can't ask for /mcp.
    owner.client.cookies.clear()
    r = owner.client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": CLIENT,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": f"{ORIGIN}/mcp",
        },
        follow_redirects=False,
    )
    assert "error=invalid_target" in r.headers["location"]


def test_account_security_is_web_only(team: Team) -> None:
    owner = team[0]
    access = _sign_in(owner)["access_token"]
    for method, path, body in [
        ("POST", "/api/v1/auth/password", {"current_password": PASSWORD, "new_password": "x"}),
        ("GET", "/api/v1/auth/sessions", None),
        ("GET", "/api/v1/account/apps", None),
        ("GET", "/api/v1/ai/connections", None),
        ("GET", "/api/v1/keys", None),
        ("GET", "/api/v1/auth/session", None),
        ("POST", "/api/v1/auth/logout", None),
    ]:
        r = _api(owner, method, path, access, json=body)
        assert r.status_code == 403, (path, r.status_code)
        assert "on the web" in r.text, path


def test_refresh_rotates_and_reuse_ends_the_sign_in(team: Team) -> None:
    owner = team[0]
    tokens = _sign_in(owner)
    first = _token(owner, grant_type="refresh_token", refresh_token=tokens["refresh_token"])
    assert first.status_code == 200, first.text
    fresh = first.json()["access_token"]
    assert fresh.startswith("phv_aat_")
    assert _api(owner, "GET", "/api/v1/projects", fresh).status_code == 200
    reuse = _token(owner, grant_type="refresh_token", refresh_token=tokens["refresh_token"])
    assert reuse.status_code == 400
    assert _api(owner, "GET", "/api/v1/projects", fresh).status_code == 401


def test_signed_in_apps_one_per_device_and_sign_out(team: Team) -> None:
    owner = team[0]
    phone = _sign_in(owner, "Ann's iPhone")["access_token"]
    ipad = _sign_in(owner, "Ann's iPad")["access_token"]
    owner._cookie()
    apps = owner.client.get("/api/v1/account/apps").json()
    assert sorted(a["device_name"] for a in apps) == ["Ann's iPad", "Ann's iPhone"]
    assert all(a["app_name"] == "PlanHaven for iPhone" for a in apps)
    # Not an AI connection.
    assert owner.client.get("/api/v1/ai/connections").json() == []
    ipad_id = next(a["id"] for a in apps if a["device_name"] == "Ann's iPad")
    owner._cookie()
    r = owner.client.delete(f"/api/v1/account/apps/{ipad_id}", headers=owner.h)
    assert r.status_code == 204
    assert _api(owner, "GET", "/api/v1/projects", ipad).status_code == 401
    assert _api(owner, "GET", "/api/v1/projects", phone).status_code == 200
    # The app signing itself out (RFC 7009) also ends its sign-in.
    tokens = _sign_in(owner, "Spare phone")
    owner.client.cookies.clear()
    owner.client.post("/oauth/revoke", data={"token": tokens["refresh_token"]})
    assert _api(owner, "GET", "/api/v1/projects", tokens["access_token"]).status_code == 401
    owner._cookie()
    names = [a["device_name"] for a in owner.client.get("/api/v1/account/apps").json()]
    assert names == ["Ann's iPhone"]


def test_password_change_and_sign_out_everywhere_end_app_sign_ins(team: Team) -> None:
    owner = team[0]
    access = _sign_in(owner)["access_token"]
    owner._cookie()
    r = owner.client.post("/api/v1/auth/sessions/revoke-others", headers=owner.h)
    assert r.status_code == 204
    assert _api(owner, "GET", "/api/v1/projects", access).status_code == 401
    access = _sign_in(owner)["access_token"]
    owner._cookie()
    r = owner.client.post(
        "/api/v1/auth/password",
        headers=owner.h,
        json={"current_password": PASSWORD, "new_password": PASSWORD + " and more"},
    )
    assert r.status_code == 204, r.text
    assert _api(owner, "GET", "/api/v1/projects", access).status_code == 401


def test_live_tickets_work_once_and_not_late(team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, _, _, pid, _ = team
    access = _sign_in(owner)["access_token"]
    # A browser session doesn't need (or get) a ticket.
    owner._cookie()
    assert owner.client.post("/api/v1/live/ticket", headers=owner.h).status_code == 403
    ticket = _api(owner, "POST", "/api/v1/live/ticket", access).json()["ticket"]
    assert ticket.startswith("phv_wst_")
    owner.client.cookies.clear()
    path = f"/api/v1/live/projects/{pid}?ticket={ticket}"
    with owner.client.websocket_connect(path) as ws:
        owner._cookie()
        owner.client.post(f"/api/v1/projects/{pid}/tasks", headers=owner.h, json={"title": "x"})
        assert "tasks" in ws.receive_text()
    # Used once.
    owner.client.cookies.clear()
    with pytest.raises(WebSocketDisconnect), owner.client.websocket_connect(path) as ws:
        ws.receive_text()
    # Late: a ticket that has already run out.
    monkeypatch.setattr(oauth_store, "TICKET_SECONDS", -1)
    late = _api(owner, "POST", "/api/v1/live/ticket", access).json()["ticket"]
    monkeypatch.undo()
    owner.client.cookies.clear()
    with (
        pytest.raises(WebSocketDisconnect),
        owner.client.websocket_connect(f"/api/v1/live/me?ticket={late}") as ws,
    ):
        ws.receive_text()
    # From another site's page.
    other = _api(owner, "POST", "/api/v1/live/ticket", access).json()["ticket"]
    owner.client.cookies.clear()
    with (
        pytest.raises(WebSocketDisconnect),
        owner.client.websocket_connect(
            f"/api/v1/live/me?ticket={other}", headers={"origin": "https://evil.example"}
        ) as ws,
    ):
        ws.receive_text()

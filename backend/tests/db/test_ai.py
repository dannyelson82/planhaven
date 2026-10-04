"""AI apps (ADR 0019, A§12): OAuth sign-in, the MCP endpoint, suggestions and undo."""

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.db import team as setup
from tests.db.team import ORIGIN, U

pytestmark = pytest.mark.db

team = setup.team  # owner, viewer, stranger, project, note

type Team = tuple[U, U, U, str, str]
REDIRECT = "https://ai.example.com/callback"


def _verifier() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _register(u: U) -> str:
    u.client.cookies.clear()
    r = u.client.post(
        "/oauth/register",
        json={"client_name": "Claude", "redirect_uris": [REDIRECT]},
        headers={"origin": "https://ai.example.com"},  # cross-origin by design
    )
    assert r.status_code == 201, r.text
    client_id: str = r.json()["client_id"]
    return client_id


def _authorize(u: U, client_id: str, challenge: str, scope: str = "projects:write") -> str:
    u.client.cookies.clear()
    r = u.client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": scope,
            "state": "xyz",
            "resource": f"{ORIGIN}/mcp",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    location = r.headers["location"]
    assert location.startswith("/connect?request=")
    return location.split("=", 1)[1]


def _approve(u: U, request_id: str, scope: str = "write", mode: str = "approve") -> str:
    u._cookie()
    r = u.client.post(
        f"/api/v1/oauth/requests/{request_id}/approve",
        headers=u.h,
        json={"scope": scope, "write_mode": mode},
    )
    assert r.status_code == 200, r.text
    q = parse_qs(urlsplit(r.json()["redirect"]).query)
    assert q["state"] == ["xyz"]
    assert q["iss"] == [ORIGIN]
    return str(q["code"][0])


def _token(u: U, **form: str) -> Any:
    u.client.cookies.clear()
    return u.client.post("/oauth/token", data=form, headers={"origin": "https://ai.example.com"})


def _connect(u: U, scope: str = "write", mode: str = "approve") -> dict[str, Any]:
    client_id = _register(u)
    verifier, challenge = _verifier()
    code = _approve(u, _authorize(u, client_id, challenge), scope, mode)
    r = _token(
        u,
        grant_type="authorization_code",
        code=code,
        redirect_uri=REDIRECT,
        client_id=client_id,
        code_verifier=verifier,
    )
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    body: dict[str, Any] = r.json()
    body["client_id"] = client_id
    return body


def _rpc(u: U, token: str, method: str, params: dict[str, Any] | None = None) -> Any:
    u.client.cookies.clear()
    return u.client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers={"authorization": f"Bearer {token}"},
    )


def _tool(u: U, token: str, name: str, **args: Any) -> dict[str, Any]:
    r = _rpc(u, token, "tools/call", {"name": name, "arguments": args})
    assert r.status_code == 200, r.text
    result: dict[str, Any] = r.json()["result"]
    return result


def test_discovery_and_unauthenticated_mcp(team: Team) -> None:
    owner = team[0]
    meta = owner.client.get("/.well-known/oauth-authorization-server").json()
    assert meta["issuer"] == ORIGIN
    assert meta["code_challenge_methods_supported"] == ["S256"]
    res = owner.client.get("/.well-known/oauth-protected-resource").json()
    assert res["resource"] == f"{ORIGIN}/mcp"

    owner.client.cookies.clear()
    r = owner.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers["www-authenticate"]
    # A signed-in browser session doesn't count.
    owner._cookie()
    assert owner.client.post("/mcp", headers=owner.h, json={}).status_code == 401
    assert owner.client.get("/mcp").status_code == 405


def test_full_flow_reads_and_hides_local_ai_only(team: Team) -> None:
    owner, _, stranger, pid, _ = team
    tokens = _connect(owner, scope="read")
    assert tokens["scope"] == "projects:read"
    access = tokens["access_token"]
    assert access.startswith("phv_oat_")

    init = _rpc(owner, access, "initialize", {"protocolVersion": "2025-06-18"}).json()
    assert init["result"]["serverInfo"]["name"] == "PlanHaven"
    names = {t["name"] for t in _rpc(owner, access, "tools/list").json()["result"]["tools"]}
    assert "planhaven_get_project" in names
    assert "planhaven_add_tasks" not in names  # read-only connection

    projects = _tool(owner, access, "planhaven_list_projects")["structuredContent"]["projects"]
    assert [p["id"] for p in projects] == [pid]
    title = projects[0]["title"]
    assert _tool(owner, access, "planhaven_get_project", project_id=pid)["isError"] is False
    hits = _tool(owner, access, "planhaven_search", query=title[:5])["structuredContent"]
    assert any(h["project_id"] == pid for h in hits["results"])

    # Writes are refused on a read-only connection.
    refused = _tool(owner, access, "planhaven_create_project", title="New")
    assert refused["isError"] is True
    assert "read-only" in refused["content"][0]["text"]

    # Local-AI-only projects are invisible to AI apps.
    owner._cookie()
    version = owner.client.get(f"/api/v1/projects/{pid}").json()["version"]
    r = owner.client.patch(
        f"/api/v1/projects/{pid}",
        headers={**owner.h, "if-match": f'"{version}"'},
        json={"local_ai_only": True},
    )
    assert r.status_code == 200, r.text
    assert _tool(owner, access, "planhaven_list_projects")["structuredContent"]["projects"] == []
    hidden = _tool(owner, access, "planhaven_get_project", project_id=pid)
    assert hidden["isError"] is True
    hits = _tool(owner, access, "planhaven_search", query=title[:5])["structuredContent"]
    assert hits["results"] == []

    # Someone else's project is never visible.
    other = _connect(stranger, scope="read")["access_token"]
    assert _tool(stranger, other, "planhaven_get_project", project_id=pid)["isError"] is True


def test_codes_and_refresh_tokens_work_once(team: Team) -> None:
    owner = team[0]
    client_id = _register(owner)
    verifier, challenge = _verifier()
    code = _approve(owner, _authorize(owner, client_id, challenge))

    wrong = _token(
        owner,
        grant_type="authorization_code",
        code=code,
        redirect_uri=REDIRECT,
        client_id=client_id,
        code_verifier=_verifier()[0],  # not the one the challenge was made from
    )
    assert wrong.status_code == 400
    assert wrong.json()["error"] == "invalid_grant"
    # The code was spent by the failed try; using it again ends the connection.
    again = _token(
        owner,
        grant_type="authorization_code",
        code=code,
        redirect_uri=REDIRECT,
        client_id=client_id,
        code_verifier=verifier,
    )
    assert again.status_code == 400

    tokens = _connect(owner)
    first = _token(
        owner,
        grant_type="refresh_token",
        refresh_token=tokens["refresh_token"],
        client_id=tokens["client_id"],
    )
    assert first.status_code == 200, first.text
    new_access = first.json()["access_token"]
    assert _rpc(owner, new_access, "ping").status_code == 200
    # Reusing the old refresh token (stolen?) ends the whole family.
    reuse = _token(
        owner,
        grant_type="refresh_token",
        refresh_token=tokens["refresh_token"],
        client_id=tokens["client_id"],
    )
    assert reuse.status_code == 400
    assert _rpc(owner, new_access, "ping").status_code == 401


def test_bad_authorize_requests(team: Team) -> None:
    owner = team[0]
    owner.client.cookies.clear()
    r = owner.client.get("/oauth/authorize", params={"client_id": "nope"}, follow_redirects=False)
    assert r.headers["location"] == "/connect?problem=unknown"
    client_id = _register(owner)
    r = owner.client.get(
        "/oauth/authorize",
        params={"client_id": client_id, "redirect_uri": "https://evil.example.net/cb"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/connect?problem=unknown"  # never to an unknown address
    r = owner.client.get(
        "/oauth/authorize",
        params={"client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT},
        follow_redirects=False,
    )
    assert r.headers["location"].startswith(REDIRECT + "?error=invalid_request")
    bad = owner.client.post("/oauth/register", json={"redirect_uris": ["http://ai.example.com/cb"]})
    assert bad.status_code == 400


def test_approve_first_then_undo(team: Team) -> None:
    owner, _, _, pid, _ = team
    access = _connect(owner, mode="approve")["access_token"]
    result = _tool(
        owner,
        access,
        "planhaven_add_tasks",
        project_id=pid,
        tasks=[{"title": "Buy filters"}, {"title": "Book a mechanic"}],
    )
    assert result["structuredContent"]["status"] == "waiting_for_approval"
    owner._cookie()
    assert all(t["title"] != "Buy filters" for t in _tasks(owner, pid))

    pending = owner.client.get("/api/v1/ai/suggestions").json()
    assert len(pending) == 1
    assert pending[0]["client_name"] == "Claude"
    unread = owner.client.get("/api/v1/notifications").json()
    assert any(n["kind"] == "ai_suggestion" for n in _items(unread))
    assert any(n["kind"] == "security_change" for n in _items(unread))  # told it connected

    r = owner.client.post(f"/api/v1/ai/suggestions/{pending[0]['id']}/approve", headers=owner.h)
    assert r.json() == {"status": "approved"}
    assert {"Buy filters", "Book a mechanic"} <= {t["title"] for t in _tasks(owner, pid)}

    changes = owner.client.get("/api/v1/ai/changes").json()
    assert changes[0]["kind"] == "tasks_added"
    r = owner.client.post(f"/api/v1/ai/changes/{changes[0]['id']}/undo", headers=owner.h)
    assert r.status_code == 204
    assert all(t["title"] != "Buy filters" for t in _tasks(owner, pid))
    # Undo works once.
    r = owner.client.post(f"/api/v1/ai/changes/{changes[0]['id']}/undo", headers=owner.h)
    assert r.status_code == 404


def test_apply_mode_viewer_and_disconnect(team: Team) -> None:
    owner, viewer, _, pid, _ = team
    access = _connect(owner, mode="apply")["access_token"]
    done = _tool(owner, access, "planhaven_add_note", project_id=pid, title="Plan", text="- one")
    assert done["structuredContent"]["status"] == "done", done
    owner._cookie()
    assert owner.client.get("/api/v1/ai/changes").json()[0]["kind"] == "note_added"

    # A viewer's AI app can't change what the viewer can't.
    viewer_access = _connect(viewer, mode="apply")["access_token"]
    refused = _tool(
        viewer, viewer_access, "planhaven_add_note", project_id=pid, title="x", text="y"
    )
    assert refused["isError"] is True

    # Another person can't see or end this connection.
    owner._cookie()
    grants = owner.client.get("/api/v1/ai/connections").json()
    assert len(grants) == 1
    viewer._cookie()
    r = viewer.client.delete(f"/api/v1/ai/connections/{grants[0]['id']}", headers=viewer.h)
    assert r.status_code == 404

    # Narrowing needs nothing more; disconnecting ends the token at once.
    owner._cookie()
    r = owner.client.patch(
        f"/api/v1/ai/connections/{grants[0]['id']}",
        headers=owner.h,
        json={"scope": "read", "write_mode": "approve"},
    )
    assert r.status_code == 204
    names = {t["name"] for t in _rpc(owner, access, "tools/list").json()["result"]["tools"]}
    assert "planhaven_add_note" not in names
    owner._cookie()
    r = owner.client.delete(f"/api/v1/ai/connections/{grants[0]['id']}", headers=owner.h)
    assert r.status_code == 204
    assert _rpc(owner, access, "ping").status_code == 401


def test_foreign_origin_refused_on_mcp(team: Team) -> None:
    owner = team[0]
    access = _connect(owner, scope="read")["access_token"]
    owner.client.cookies.clear()
    r = owner.client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"authorization": f"Bearer {access}", "origin": "https://evil.example.net"},
    )
    assert r.status_code == 403


def _tasks(u: U, pid: str) -> list[dict[str, Any]]:
    u._cookie()
    body = u.client.get(f"/api/v1/projects/{pid}/tasks").json()
    return _items(body)


def _items(body: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = body["items"] if isinstance(body, dict) else body
    return items


def test_token_endpoint_rejects_junk(team: Team) -> None:
    owner = team[0]
    owner.client.cookies.clear()
    many = "&".join(f"f{i}=x" for i in range(30))
    r = owner.client.post(
        "/oauth/token",
        content=many,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"
    r = owner.client.post("/oauth/token", data={"grant_type": "password"})
    assert r.json()["error"] == "unsupported_grant_type"

"""Behavioural half of the authorization matrix: every route called as every kind of
principal must be allowed or refused exactly as tests/authz_matrix.py says."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.db.database import Database
from app.main import create_app
from tests.authz_matrix import BODIES, EXPECT, MATRIX
from tests.db.conftest import _settings
from tests.db.test_auth import GOOD_PASSWORD, ORIGIN, _setup_admin
from tests.db.test_mfa import enroll_totp

pytestmark = [pytest.mark.db, pytest.mark.anyio]

PRINCIPALS = ("anon", "partial", "stale", "fresh", "admin_stale", "admin_fresh")


@dataclass
class Caller:
    client: httpx2.AsyncClient
    csrf: str | None


def _client(app: FastAPI, n: int) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app, client=(f"198.51.100.{n}", 1)),
        base_url=ORIGIN,
        headers={"origin": ORIGIN},
    )


async def _invite_user(app: FastAPI, admin: Caller, n: int, email: str) -> Caller:
    r = await admin.client.post(
        "/api/v1/admin/invites", headers={"x-csrf-token": admin.csrf or ""}, json={}
    )
    token = r.json()["url"].split("#", 1)[1]
    c = _client(app, n)
    joined = await c.post(
        "/api/v1/invites/accept",
        json={
            "token": token,
            "email": email,
            "display_name": email.split("@")[0],
            "password": GOOD_PASSWORD,
        },
    )
    csrf = joined.json()["csrf_token"]
    await enroll_totp(c, csrf)
    return Caller(c, csrf)


async def _make_stale(db: Database, email: str) -> None:
    async with db.system_transaction() as conn:
        await conn.execute(
            text(
                "UPDATE sessions SET reauth_at = now() - interval '6 minutes' "
                "WHERE user_id = (SELECT id FROM users WHERE email = :e)"
            ),
            {"e": email},
        )


@pytest.fixture
async def callers(owner_db: Database, db: Database) -> AsyncIterator[dict[str, Caller]]:
    async with owner_db.anonymous_transaction() as conn:
        await conn.execute(text("TRUNCATE users, sessions, setup_tokens CASCADE"))
    app = create_app(_settings())

    admin_c = _client(app, 1)
    csrf = (await _setup_admin(admin_c, db)).json()["csrf_token"]
    await enroll_totp(admin_c, csrf)
    admin = Caller(admin_c, csrf)

    admin2 = await _invite_user(app, admin, 2, "admin2@example.com")
    users = {(u["email"]): u["id"] for u in (await admin_c.get("/api/v1/admin/users")).json()}
    await admin_c.post(
        f"/api/v1/admin/users/{users['admin2@example.com']}/admin",
        headers={"x-csrf-token": csrf},
        json={"value": True},
    )
    fresh = await _invite_user(app, admin, 3, "fresh@example.com")
    stale = await _invite_user(app, admin, 4, "stale@example.com")
    partial_user = await _invite_user(app, admin, 5, "partial@example.com")
    partial_user.client.cookies.clear()
    login = await partial_user.client.post(
        "/api/v1/auth/login", json={"email": "partial@example.com", "password": GOOD_PASSWORD}
    )
    partial = Caller(partial_user.client, login.json()["csrf_token"])
    await _make_stale(db, "stale@example.com")
    await _make_stale(db, "admin2@example.com")

    result = {
        "anon": Caller(_client(app, 6), None),
        "partial": partial,
        "stale": stale,
        "fresh": fresh,
        "admin_stale": admin2,
        "admin_fresh": admin,
    }
    yield result
    for caller in result.values():
        await caller.client.aclose()
    await app.state.db.dispose()


def _url(path: str) -> str:
    out = path
    while "{" in out:
        start, end = out.index("{"), out.index("}")
        out = out[:start] + str(uuid.uuid4()) + out[end + 1 :]
    return out


async def _call(caller: Caller, method: str, path: str, *, csrf: bool = True) -> int:
    headers = {"x-csrf-token": caller.csrf} if (csrf and caller.csrf) else {}
    kwargs: dict[str, object] = {"headers": headers}
    if method in ("POST", "PUT", "PATCH"):
        kwargs["json"] = BODIES.get((method, path), {})
    response = await caller.client.request(method, _url(path), **kwargs)  # type: ignore[arg-type]
    return response.status_code


def _ordered() -> list[tuple[str, str]]:
    # Sign-out last: it ends the caller's session.
    return sorted(MATRIX, key=lambda k: (k == ("POST", "/api/v1/auth/logout"), k))


async def test_every_route_as_every_principal(callers: dict[str, Caller]) -> None:
    failures = []
    for method, path in _ordered():
        cls = MATRIX[(method, path)]
        for principal in PRINCIPALS:
            expected = EXPECT[cls][principal]
            status = await _call(callers[principal], method, path)
            if expected == "ok":
                refused = {401, 403} | ({404} if cls == "admin" and "{" not in path else set())
                ok = status not in refused
            else:
                ok = status == expected
            if not ok:
                failures.append(
                    f"{method} {path} as {principal}: got {status}, expected {expected}"
                )
    assert failures == []


async def test_unsafe_session_routes_need_csrf(callers: dict[str, Caller]) -> None:
    failures = []
    for (method, path), cls in MATRIX.items():
        if method == "GET" or cls in ("public", "public_origin"):
            continue
        if (method, path) == ("POST", "/api/v1/auth/logout"):
            continue
        status = await _call(callers["admin_fresh"], method, path, csrf=False)
        if status != 403:
            failures.append(f"{method} {path}: {status} without CSRF token")
    assert failures == []


async def test_public_unsafe_routes_need_our_origin(callers: dict[str, Caller]) -> None:
    anon = callers["anon"].client
    failures = []
    for (method, path), cls in MATRIX.items():
        if cls != "public_origin":
            continue
        response = await anon.request(
            method,
            _url(path),
            json=BODIES.get((method, path), {}),
            headers={"origin": "https://evil.example"},
        )
        if response.status_code != 403:
            failures.append(f"{method} {path}: {response.status_code} from a foreign origin")
    assert failures == []

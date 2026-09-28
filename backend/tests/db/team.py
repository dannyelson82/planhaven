"""Shared setup for database tests: a household of three (owner/admin "Ann", a viewer and a
stranger), a project the viewer can see, and a note in it. One TestClient (one event loop);
each person keeps their own session cookie."""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database import OWNER_ROLE, Database
from app.main import create_app
from app.services import auth as auth_service
from tests.db.conftest import _settings

ORIGIN = "https://planhaven.example.com"
COOKIE = "__Host-planhaven_session"
PASSWORD = "correct horse battery staple 42"


@dataclass
class U:
    """One person. All share a single TestClient (one event loop); each keeps its own
    session cookie, set explicitly on every request."""

    client: TestClient
    csrf: str
    id: str
    token: str

    @property
    def h(self) -> dict[str, str]:
        return {"x-csrf-token": self.csrf}

    def _cookie(self) -> None:
        self.client.cookies.clear()
        self.client.cookies.set(COOKIE, self.token)

    def get(self, path: str, **kw: Any) -> Any:
        self._cookie()
        return self.client.get(path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        self._cookie()
        return self.client.post(path, **kw)

    def put(self, path: str, **kw: Any) -> Any:
        self._cookie()
        return self.client.put(path, **kw)

    def ws(self, path: str, origin: str = ORIGIN) -> Any:
        return self.client.websocket_connect(
            path, headers={"origin": origin, "cookie": f"{COOKIE}={self.token}"}
        )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _truncate() -> None:
    db = Database(_settings(), role=OWNER_ROLE)
    async with db.anonymous_transaction() as conn:
        await conn.execute(text("TRUNCATE users, sessions, setup_tokens CASCADE"))
    await db.dispose()


async def _setup_token() -> str:
    db = Database(_settings())
    token = await auth_service.issue_setup_token(db)
    await db.dispose()
    assert token
    return token


def _enroll(u: U) -> None:
    secret = u.post("/api/v1/auth/mfa/totp/enroll", headers=u.h).json()["secret"]
    r = u.post(
        "/api/v1/auth/mfa/totp/confirm", headers=u.h, json={"code": pyotp.TOTP(secret).now()}
    )
    assert r.status_code == 200, r.text


@pytest.fixture
def team() -> Iterator[tuple[U, U, U, str, str]]:
    """(owner, viewer, stranger, project_id, note_id)"""
    _run(_truncate())
    app = create_app(_settings())
    with TestClient(app, base_url=ORIGIN, headers={"origin": ORIGIN}) as c:
        r = c.post(
            "/api/v1/setup",
            json={
                "setup_token": _run(_setup_token()),
                "email": "a@example.com",
                "display_name": "Ann",
                "password": PASSWORD,
            },
        )
        assert r.status_code == 201, r.text
        owner = U(c, r.json()["csrf_token"], r.json()["user"]["id"], r.cookies[COOKIE])
        _enroll(owner)
        others = []
        for name in ("viewer", "stranger"):
            url = owner.post("/api/v1/admin/invites", headers=owner.h, json={}).json()["url"]
            c.cookies.clear()
            j = c.post(
                "/api/v1/invites/accept",
                json={
                    "token": url.split("#")[1],
                    "email": f"{name}@example.com",
                    "display_name": name,
                    "password": PASSWORD,
                },
            )
            assert j.status_code == 201, j.text
            u = U(c, j.json()["csrf_token"], j.json()["user"]["id"], j.cookies[COOKIE])
            _enroll(u)
            others.append(u)
        viewer, stranger = others
        pid = owner.post("/api/v1/projects", headers=owner.h, json={"title": "Deck"}).json()["id"]
        owner.post(
            f"/api/v1/projects/{pid}/members",
            headers=owner.h,
            json={"user_id": viewer.id, "role": "viewer"},
        )
        nid = owner.post(
            f"/api/v1/projects/{pid}/notes", headers=owner.h, json={"title": "Wiring plan"}
        ).json()["id"]
        yield owner, viewer, stranger, pid, nid

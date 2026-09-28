"""Real-time co-editing and live updates over WebSockets (ADR 0011, SECURITY.md §7.15).

Uses Starlette's TestClient (it speaks WebSocket); a pycrdt document plays the browser."""

import asyncio
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pycrdt
import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app.db.database import OWNER_ROLE, Database
from app.main import create_app
from app.services import auth as auth_service
from app.services import live
from app.services import notes as note_service
from tests.db.conftest import _settings

pytestmark = pytest.mark.db

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


def _sync(ws: Any, doc: pycrdt.Doc[Any]) -> None:
    """Client side of the opening handshake: answer the server's step 1, send our own."""
    step1 = ws.receive_bytes()
    reply = pycrdt.handle_sync_message(step1[1:], doc)
    if reply:
        ws.send_bytes(reply)
    ws.send_bytes(pycrdt.create_sync_message(doc))
    step2 = ws.receive_bytes()
    pycrdt.handle_sync_message(step2[1:], doc)


def _edit(doc: pycrdt.Doc[Any], words: str) -> bytes:
    updates: list[bytes] = []
    sub = doc.observe(lambda e: updates.append(e.update))
    doc.get("t", type=pycrdt.Text).__iadd__(words)
    doc.unobserve(sub)
    return pycrdt.create_update_message(updates[0])


def test_edits_are_shared_saved_and_attributed(team: tuple[U, U, U, str, str]) -> None:
    owner, viewer, _, _, nid = team
    path = f"/api/v1/collab/notes/{nid}"
    with owner.ws(path) as a, viewer.ws(path) as b:
        doc_a: pycrdt.Doc[Any] = pycrdt.Doc()
        doc_b: pycrdt.Doc[Any] = pycrdt.Doc()
        _sync(a, doc_a)
        _sync(b, doc_b)
        a.send_bytes(_edit(doc_a, "Run 12V to the dock"))
        pycrdt.handle_sync_message(b.receive_bytes()[1:], doc_b)
        assert str(doc_b.get("t", type=pycrdt.Text)) == "Run 12V to the dock"
    # Everyone left; a fresh room loads the saved state from the database.
    with viewer.ws(path) as c:
        doc_c: pycrdt.Doc[Any] = pycrdt.Doc()
        _sync(c, doc_c)
        assert str(doc_c.get("t", type=pycrdt.Text)) == "Run 12V to the dock"


def test_viewers_cannot_edit(
    team: tuple[U, U, U, str, str], caplog: pytest.LogCaptureFixture
) -> None:
    _, viewer, _, _, nid = team
    caplog.set_level(logging.INFO, logger="planhaven.security")
    with viewer.ws(f"/api/v1/collab/notes/{nid}") as ws:
        doc: pycrdt.Doc[Any] = pycrdt.Doc()
        _sync(ws, doc)
        ws.send_bytes(_edit(doc, "sneaky"))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_bytes()
        assert closed.value.code == 4403
    # The attempt is a security event (never with the update's content).
    assert "collab_refused" in [getattr(r, "event", None) for r in caplog.records]


@pytest.mark.parametrize("who", ["anonymous", "foreign-origin", "stranger"])
def test_handshake_refusals(team: tuple[U, U, U, str, str], who: str) -> None:
    owner, _, stranger, _, nid = team
    path = f"/api/v1/collab/notes/{nid}"
    if who == "anonymous":
        owner.client.cookies.clear()  # the shared client must carry no session cookie
        connect = owner.client.websocket_connect(path, headers={"origin": ORIGIN})
    elif who == "foreign-origin":
        connect = owner.ws(path, origin="https://evil.example")
    else:
        connect = stranger.ws(path)
    with pytest.raises(WebSocketDisconnect) as refused:
        _open_and_read(connect)
    assert refused.value.code in (4401, 4404)


def _open_and_read(connect: Any) -> None:
    with connect as ws:
        ws.receive_bytes()


def test_oversized_messages_close_the_connection(team: tuple[U, U, U, str, str]) -> None:
    owner, _, _, _, nid = team
    with owner.ws(f"/api/v1/collab/notes/{nid}") as ws:
        _sync(ws, pycrdt.Doc())
        ws.send_bytes(b"\x01" + b"x" * 300_000)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_bytes()
        assert closed.value.code == 4413


def test_live_updates_tell_open_pages_what_changed(team: tuple[U, U, U, str, str]) -> None:
    owner, viewer, _, pid, _ = team
    with viewer.ws(f"/api/v1/live/projects/{pid}") as ws:
        owner.client.post(
            f"/api/v1/projects/{pid}/tasks", headers=owner.h, json={"title": "Buy LED strips"}
        )
        assert ws.receive_json() == {"kind": "tasks"}


def test_open_sockets_per_user_are_capped(
    team: tuple[U, U, U, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _, pid, _ = team
    monkeypatch.setattr(live, "MAX_SOCKETS_PER_USER", 1)
    with owner.ws(f"/api/v1/live/projects/{pid}"):
        with (
            pytest.raises(WebSocketDisconnect) as refused,
            owner.ws(f"/api/v1/live/projects/{pid}"),
        ):
            pass
        assert refused.value.code == 4429
    # Closing frees the slot.
    with owner.ws(f"/api/v1/live/projects/{pid}"):
        pass


def test_note_rest_roles(team: tuple[U, U, U, str, str]) -> None:
    owner, viewer, stranger, pid, nid = team
    assert viewer.get(f"/api/v1/notes/{nid}").json()["can_edit"] is False
    assert owner.get(f"/api/v1/notes/{nid}").json()["can_edit"] is True
    assert (
        viewer.put(f"/api/v1/notes/{nid}/text", headers=viewer.h, json={"text": "x"}).status_code
        == 403
    )
    assert stranger.get(f"/api/v1/notes/{nid}").status_code == 404
    assert (
        owner.put(
            f"/api/v1/notes/{nid}/text", headers=owner.h, json={"text": "Run 12V to the dock"}
        ).status_code
        == 204
    )
    listed = owner.get(f"/api/v1/projects/{pid}/notes").json()
    assert listed[0]["text_content"] == "Run 12V to the dock"


def test_message_rate_limit_closes_the_connection(
    team: tuple[U, U, U, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _, _, nid = team
    monkeypatch.setattr(note_service, "MESSAGES_PER_WINDOW", 3)
    with owner.ws(f"/api/v1/collab/notes/{nid}") as ws:
        _sync(ws, pycrdt.Doc())
        for _ in range(10):
            ws.send_bytes(b"\x01\x00")  # tiny awareness messages
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_bytes()
        assert closed.value.code == 4429


def test_sharing_changes_apply_to_open_notes_at_once(team: tuple[U, U, U, str, str]) -> None:
    owner, viewer, _, pid, nid = team
    # Promoted while connected: the next edit is accepted.
    with viewer.ws(f"/api/v1/collab/notes/{nid}") as ws:
        doc: pycrdt.Doc[Any] = pycrdt.Doc()
        _sync(ws, doc)
        owner._cookie()
        r = owner.client.patch(
            f"/api/v1/projects/{pid}/members/{viewer.id}", headers=owner.h, json={"role": "editor"}
        )
        assert r.status_code == 204, r.text
        ws.send_bytes(_edit(doc, "now allowed"))
        ws.send_bytes(pycrdt.create_sync_message(doc))  # answered only if the edit was accepted
        ws.receive_bytes()
    with owner.ws(f"/api/v1/collab/notes/{nid}") as ws:
        check: pycrdt.Doc[Any] = pycrdt.Doc()
        _sync(ws, check)
        assert "now allowed" in str(check.get("t", type=pycrdt.Text))

    # Removed while connected: disconnected straight away, not at the next periodic check.
    with viewer.ws(f"/api/v1/collab/notes/{nid}") as ws:
        _sync(ws, pycrdt.Doc())
        owner._cookie()
        r = owner.client.delete(f"/api/v1/projects/{pid}/members/{viewer.id}", headers=owner.h)
        assert r.status_code == 204, r.text
        started = time.monotonic()
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_bytes()
        assert closed.value.code == 4403
        assert time.monotonic() - started < 5

"""Live updates for open project pages over a WebSocket (ADR 0011, SECURITY.md §7.15)."""

import time

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api import live as live_api
from app.services import live
from tests.db import team as setup
from tests.db.team import ORIGIN, U

pytestmark = pytest.mark.db

team = setup.team

type Team = tuple[U, U, U, str, str]


@pytest.mark.parametrize("who", ["anonymous", "foreign-origin", "stranger"])
def test_handshake_refusals(team: Team, who: str) -> None:
    owner, _, stranger, pid, _ = team
    path = f"/api/v1/live/projects/{pid}"
    if who == "anonymous":
        owner.client.cookies.clear()  # the shared client must carry no session cookie
        connect = owner.client.websocket_connect(path, headers={"origin": ORIGIN})
    elif who == "foreign-origin":
        connect = owner.ws(path, origin="https://evil.example")
    else:
        connect = stranger.ws(path)
    with pytest.raises(WebSocketDisconnect) as refused, connect as ws:
        ws.receive_text()
    assert refused.value.code in (4401, 4404)


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


def test_open_project_pages_hear_about_note_saves(team: Team) -> None:
    owner, viewer, _, pid, nid = team
    version = owner.get(f"/api/v1/notes/{nid}").json()["version"]
    with viewer.ws(f"/api/v1/live/projects/{pid}") as ws:
        owner._cookie()
        owner.client.put(
            f"/api/v1/notes/{nid}",
            headers={**owner.h, "if-match": f'"{version}"'},
            json={"title": "Wiring plan", "content": {"type": "doc", "content": []}},
        )
        assert ws.receive_json() == {"kind": "notes"}


def test_removed_member_is_disconnected_while_changes_keep_coming(
    team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, viewer, _, pid, _ = team
    monkeypatch.setattr(live_api, "RECHECK_SECONDS", 0.2)
    with viewer.ws(f"/api/v1/live/projects/{pid}") as ws:
        owner._cookie()
        gone = owner.client.delete(f"/api/v1/projects/{pid}/members/{viewer.id}", headers=owner.h)
        assert gone.status_code == 204

        def busy_project() -> None:  # a change every 50 ms, until the socket is closed
            for i in range(50):
                time.sleep(0.05)
                owner.post(
                    f"/api/v1/projects/{pid}/tasks", headers=owner.h, json={"title": f"T{i}"}
                )
                ws.receive_json()

        with pytest.raises(WebSocketDisconnect) as closed:
            busy_project()
        assert closed.value.code == 4403

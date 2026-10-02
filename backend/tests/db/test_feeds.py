"""Calendar feed and Reminders sync keys (A§13.1, A§13.2, SECURITY.md §7.3)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core import security_log
from app.services import limits
from tests.db import team as setup
from tests.db.team import U

pytestmark = pytest.mark.db

team = setup.team  # owner, viewer, stranger, project, note

type Team = tuple[U, U, U, str, str]


def _req(u: U, method: str, path: str, **kw: Any) -> Any:
    u._cookie()
    return u.client.request(method, path, headers={**u.h, **kw.pop("headers", {})}, **kw)


def _key(u: U, kind: str, **extra: Any) -> dict[str, Any]:
    r = _req(u, "POST", "/api/v1/keys", json={"kind": kind, "label": "Phone", **extra})
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def test_calendar_feed(team: Team) -> None:
    owner, viewer, _, pid, _ = team
    due = (datetime.now(UTC) + timedelta(days=2)).replace(microsecond=0)
    _req(
        owner,
        "POST",
        f"/api/v1/projects/{pid}/tasks",
        json={"title": "Change oil", "notes": "5W-30, 6 quarts", "due_at": due.isoformat()},
    )
    key = _key(owner, "ics")
    assert key["key"].startswith("phv_ics_")
    path = key["url"].split("://", 1)[1].split("/", 1)[1]

    owner.client.cookies.clear()  # a calendar app has no session
    r = owner.client.get(f"/{path}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    assert "SUMMARY:Change oil" in r.text
    assert "6 quarts" not in r.text  # titles only by default
    assert owner.client.get("/ics/phv_ics_not-a-real-key.ics").status_code == 404

    # Notes only when chosen; a new link replaces the old one.
    assert (
        _req(owner, "PUT", "/api/v1/keys/feed-details", json={"details": True}).status_code == 204
    )
    owner.client.cookies.clear()
    assert "6 quarts" in owner.client.get(f"/{path}").text
    _key(owner, "ics")
    owner.client.cookies.clear()
    assert owner.client.get(f"/{path}").status_code == 404

    # A viewer's feed doesn't include tasks they can't change.
    viewer_path = _key(viewer, "ics")["url"].split("://", 1)[1].split("/", 1)[1]
    viewer.client.cookies.clear()
    assert "Change oil" not in viewer.client.get(f"/{viewer_path}").text


def test_reminders_sync(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    lid = _req(owner, "POST", f"/api/v1/projects/{pid}/lists", json={"title": "Groceries"}).json()[
        "id"
    ]
    milk = _req(
        owner, "POST", f"/api/v1/lists/{lid}/items", json={"text": "Milk", "quantity": "2"}
    ).json()
    _req(owner, "POST", f"/api/v1/lists/{lid}/items", json={"text": "Bread"})
    assert (
        _req(
            owner, "PUT", f"/api/v1/lists/{lid}/sync", json={"reminders_name": "Groceries"}
        ).status_code
        == 204
    )
    # Not a list you can't see.
    assert (
        _req(stranger, "PUT", f"/api/v1/lists/{lid}/sync", json={"reminders_name": "x"}).status_code
        == 404
    )

    key = _key(owner, "sync")["key"]
    auth = {"authorization": f"Bearer {key}"}
    owner.client.cookies.clear()
    pull = owner.client.get("/api/v1/sync/pull", headers=auth).json()
    assert sorted(i["title"] for i in pull["items"]) == ["Bread", "Milk (2)"]
    assert all(
        i["list"] == "Groceries" and i["url"].endswith(f"/i/{i['id']}") for i in pull["items"]
    )

    # One Reminders list at a time (one block of the Shortcut).
    one = owner.client.get("/api/v1/sync/pull", headers=auth, params={"list": "Groceries"}).json()
    assert len(one["items"]) == 2
    none = owner.client.get("/api/v1/sync/pull", headers=auth, params={"list": "Hardware"}).json()
    assert none["items"] == []

    # Ticked on the phone; the next pull sends only what changed since.
    # The Shortcut sends the ticked reminders' notes (their links) as text.
    notes = f"Opens in PlanHaven: https://planhaven.example.com/i/{milk['id']}\n"
    r = owner.client.post("/api/v1/sync/push", headers=auth, json={"done_text": notes})
    assert r.json() == {"changed": 1}
    again = owner.client.get(
        "/api/v1/sync/pull", headers=auth, params={"cursor": pull["cursor"]}
    ).json()
    assert [(i["title"], i["done"], i["action"]) for i in again["items"]] == [
        ("Milk (2)", True, "remove")
    ]

    # A sync key does nothing else; a session doesn't open sync; bad keys don't either.
    assert owner.client.get(f"/api/v1/lists/{lid}", headers=auth).status_code == 401
    assert _req(owner, "GET", "/api/v1/sync/pull").status_code == 401
    assert (
        owner.client.get(
            "/api/v1/sync/pull", headers={"authorization": "Bearer phv_sync_nope"}
        ).status_code
        == 401
    )
    # Items outside the synced lists are ignored.
    other = _req(owner, "POST", f"/api/v1/projects/{pid}/lists", json={"title": "Other"}).json()[
        "id"
    ]
    hidden = _req(owner, "POST", f"/api/v1/lists/{other}/items", json={"text": "Secret"}).json()
    owner.client.cookies.clear()
    assert owner.client.post(
        "/api/v1/sync/push", headers=auth, json={"done": [hidden["id"]]}
    ).json() == {"changed": 0}

    # Revoked: stops working at once.
    kid = next(k["id"] for k in _req(owner, "GET", "/api/v1/keys").json() if k["kind"] == "sync")
    assert _req(owner, "DELETE", f"/api/v1/keys/{kid}").status_code == 204
    owner.client.cookies.clear()
    assert owner.client.get("/api/v1/sync/pull", headers=auth).status_code == 401
    # Keys are each person's own.
    assert _req(viewer, "DELETE", f"/api/v1/keys/{kid}").status_code == 404


def test_failed_keys_are_logged_and_limited(team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, _, _, _, _ = team
    logged: list[tuple[str, str]] = []
    monkeypatch.setattr(
        security_log, "event", lambda name, **kw: logged.append((name, kw.get("kind", "")))
    )
    monkeypatch.setattr(
        limits, "KEY_FAIL_IP", limits.Limit("test-key-fail", capacity=3, per_second=0.001)
    )
    owner.client.cookies.clear()
    wrong = {"authorization": "Bearer phv_sync_" + "x" * 43}
    codes = [owner.client.get("/api/v1/sync/pull", headers=wrong).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
    assert owner.client.get("/ics/phv_ics_" + "y" * 43 + ".ics").status_code == 429
    assert ("key_failed", "sync") in logged
    assert ("key_failed", "ics") in logged


def test_sync_is_rate_limited_per_key(team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, _, _, _, _ = team
    key = _key(owner, "sync")["key"]
    monkeypatch.setattr(
        limits, "SYNC_KEY", limits.Limit("test-sync-key", capacity=2, per_second=0.001)
    )
    owner.client.cookies.clear()
    auth = {"authorization": f"Bearer {key}"}
    codes = [owner.client.get("/api/v1/sync/pull", headers=auth).status_code for _ in range(3)]
    assert codes == [200, 200, 429]

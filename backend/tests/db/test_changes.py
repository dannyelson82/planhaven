"""The change feed for offline copies (ADR 0021, phase 0.5 milestone 3)."""

import asyncio
from typing import Any

import pytest

from app.db.database import Database
from tests.db import team as setup
from tests.db.conftest import _settings
from tests.db.team import U

pytestmark = pytest.mark.db

team = setup.team

type Team = tuple[U, U, U, str, str]


def _snapshot(u: U, **params: Any) -> list[dict[str, Any]]:
    """Every page of a snapshot; also checks the pages don't overlap."""
    items: list[dict[str, Any]] = []
    after = None
    while True:
        q = dict(params)
        if after:
            q["after"] = after
        r = u.get("/api/v1/changes/snapshot", params=q)
        assert r.status_code == 200, r.text
        body = r.json()
        items += body["items"]
        after = body["after"]
        if after is None:
            break
    keys = [(i["kind"], i["id"]) for i in items]
    assert len(keys) == len(set(keys)), "a snapshot page repeated an item"
    return items


def _start(u: U) -> str:
    r = u.get("/api/v1/changes/snapshot")
    cursor: str = r.json()["changes_cursor"]
    assert cursor
    return cursor


def _changes(u: U, cursor: str) -> tuple[list[dict[str, Any]], str]:
    r = u.get("/api/v1/changes", params={"cursor": cursor})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["changes"], body["cursor"]


def test_snapshot_shows_what_each_person_can_see(team: Team) -> None:
    owner, viewer, stranger, pid, nid = team
    owner.post(f"/api/v1/projects/{pid}/tasks", headers=owner.h, json={"title": "Sand"})
    mine = {(i["kind"], i["id"]) for i in _snapshot(owner)}
    assert ("projects", pid) in mine
    assert ("notes", nid) in mine
    assert {(i["kind"], i["id"]) for i in _snapshot(viewer)} >= {("projects", pid), ("notes", nid)}
    assert _snapshot(stranger) == []
    # Small pages give the same items, in order, without repeats.
    assert {(i["kind"], i["id"]) for i in _snapshot(owner, limit=1)} == mine
    # One project only.
    scoped = _snapshot(owner, project_id=pid)
    assert {i["kind"] for i in scoped} >= {"projects", "notes", "tasks"}
    assert all(i["project_id"] == pid for i in scoped)
    note = next(i for i in scoped if i["kind"] == "notes")
    assert "content" not in note["data"]


def test_changes_upserts_and_deletes(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    cursors = {u.id: _start(u) for u in (owner, viewer, stranger)}
    task = owner.post(
        f"/api/v1/projects/{pid}/tasks", headers=owner.h, json={"title": "Prime"}
    ).json()
    seen, cursors[owner.id] = _changes(owner, cursors[owner.id])
    upsert = next(c for c in seen if c["kind"] == "tasks" and c["id"] == task["id"])
    assert upsert["op"] == "upsert"
    assert upsert["data"]["title"] == "Prime"
    assert upsert["project_id"] == pid
    viewer_seen, _ = _changes(viewer, cursors[viewer.id])
    assert any(c["id"] == task["id"] for c in viewer_seen)
    stranger_seen, _ = _changes(stranger, cursors[stranger.id])
    assert stranger_seen == []

    owner._cookie()
    assert owner.client.delete(f"/api/v1/tasks/{task['id']}", headers=owner.h).status_code == 204
    seen, cursors[owner.id] = _changes(owner, cursors[owner.id])
    assert [c["op"] for c in seen if c["id"] == task["id"]] == ["delete"]
    assert all(c["data"] is None for c in seen if c["op"] == "delete")
    # Nothing new: the same cursor comes back.
    seen, again = _changes(owner, cursors[owner.id])
    assert seen == []
    assert again == cursors[owner.id]


def test_access_lost_and_gained(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    viewer_cursor, stranger_cursor = _start(viewer), _start(stranger)
    owner._cookie()
    r = owner.client.delete(f"/api/v1/projects/{pid}/members/{viewer.id}", headers=owner.h)
    assert r.status_code == 204, r.text
    r = owner.client.post(
        f"/api/v1/projects/{pid}/members",
        headers=owner.h,
        json={"user_id": stranger.id, "role": "editor"},
    )
    assert r.status_code in (200, 201), r.text
    owner.post(f"/api/v1/projects/{pid}/tasks", headers=owner.h, json={"title": "Secret"})

    lost, _ = _changes(viewer, viewer_cursor)
    assert [(c["kind"], c["id"], c["op"]) for c in lost] == [("projects", pid, "access_lost")]
    gained, _ = _changes(stranger, stranger_cursor)
    assert ("projects", pid, "access_gained") in [(c["kind"], c["id"], c["op"]) for c in gained]
    assert any(c["kind"] == "tasks" and c["data"]["title"] == "Secret" for c in gained)
    assert {i["kind"] for i in _snapshot(stranger, project_id=pid)} >= {"projects", "tasks"}


def test_bad_and_expired_cursors(team: Team) -> None:
    owner = team[0]
    assert owner.get("/api/v1/changes", params={"cursor": "nope"}).status_code == 400
    assert owner.get("/api/v1/changes").status_code == 422
    cursor = _start(owner)
    owner.post(f"/api/v1/projects/{team[3]}/tasks", headers=owner.h, json={"title": "Old"})

    async def purge_all() -> None:
        from app.db import changes as store

        db = Database(_settings())
        async with db.system_transaction() as conn:
            await store.purge(conn, days=0)
        await db.dispose()

    asyncio.run(purge_all())
    r = owner.get("/api/v1/changes", params={"cursor": cursor})
    assert r.status_code == 410
    assert r.headers["content-type"].startswith("application/problem+json")

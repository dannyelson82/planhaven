"""Chores end to end (ADR 0013): assigned to someone who isn't a project member, done with a
photo, sent back, approved, repeating; one-off chores without proof; reminders."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.db.database import Database
from app.services import chores as chore_service
from tests.db import team as setup
from tests.db.conftest import _settings
from tests.db.team import U
from tests.test_files import jpeg_with_gps

pytestmark = pytest.mark.db

team = setup.team  # owner, viewer (project viewer), stranger (not in the project), project, note

type Team = tuple[U, U, U, str, str]


def _req(u: U, method: str, path: str, **kw: Any) -> Any:
    u._cookie()
    return u.client.request(method, path, headers={**u.h, **kw.pop("headers", {})}, **kw)


def _task(owner: U, pid: str, title: str) -> dict[str, Any]:
    r = _req(owner, "POST", f"/api/v1/projects/{pid}/tasks", json={"title": title})
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def _assign(owner: U, task: dict[str, Any], **chore: Any) -> Any:
    return _req(
        owner,
        "PUT",
        f"/api/v1/tasks/{task['id']}/chore",
        headers={"if-match": f'"{task["version"]}"'},
        json=chore,
    )


def _kinds(u: U) -> list[str]:
    return [n["kind"] for n in _req(u, "GET", "/api/v1/notifications").json()]


def test_repeating_chore_with_photo_proof(team: Team) -> None:
    owner, viewer, kid, pid, _ = team
    task = _task(owner, pid, "Take out the bins")
    due = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    # Viewers can't assign; a repeat needs a due time.
    viewer_try = {"assignee_id": kid.id, "proof": "photo"}
    assert (
        _req(
            viewer,
            "PUT",
            f"/api/v1/tasks/{task['id']}/chore",
            headers={"if-match": f'"{task["version"]}"'},
            json=viewer_try,
        ).status_code
        == 403
    )
    assert _assign(owner, task, assignee_id=kid.id, repeat_freq="weekly").status_code == 422
    r = _assign(
        owner,
        task,
        assignee_id=kid.id,
        proof="photo",
        repeat_freq="weekly",
        repeat_days=[2],
        due_at=due,
    )
    assert r.status_code == 200, r.text
    assert "chore_assigned" in _kinds(kid)

    # The kid isn't in the project: they see their chore (not the project's name), nothing else.
    mine = _req(kid, "GET", "/api/v1/chores").json()
    assert [(c["title"], c["project_title"]) for c in mine] == [("Take out the bins", None)]
    assert _req(kid, "GET", f"/api/v1/projects/{pid}/tasks").status_code == 404

    # Done: waits for the photo, then for approval.
    sub = _req(kid, "POST", f"/api/v1/tasks/{task['id']}/submissions", json={}).json()
    assert sub["status"] == "awaiting_photo"
    r = _req(
        kid,
        "PUT",
        f"/api/v1/submissions/{sub['id']}/photo",
        headers={"content-type": "application/octet-stream"},
        content=jpeg_with_gps(),
    )
    assert (r.status_code, r.json()["status"], r.json()["has_photo"]) == (200, "pending", True)
    assert "chore_submitted" in _kinds(owner)
    assert [x["chore"]["title"] for x in _req(owner, "GET", "/api/v1/chores/to-review").json()] == [
        "Take out the bins"
    ]
    # The photo: for the kid and project members; it's the cleaned copy.
    for who in (kid, owner, viewer):
        assert _req(who, "GET", f"/api/v1/submissions/{sub['id']}/photo").status_code == 200
    assert b"GPS" not in _req(owner, "GET", f"/api/v1/submissions/{sub['id']}/photo").content

    # Only the assigner (or the project's owners and editors) review; sending back needs a reason.
    review = f"/api/v1/submissions/{sub['id']}/review"
    assert _req(viewer, "POST", review, json={"approve": True}).status_code == 403
    assert _req(kid, "POST", review, json={"approve": True}).status_code == 403
    assert _req(owner, "POST", review, json={"approve": False}).status_code == 422
    r = _req(owner, "POST", review, json={"approve": False, "comment": "Recycling too"})
    assert r.json()["status"] == "sent_back"
    assert "chore_sent_back" in _kinds(kid)
    assert _req(kid, "GET", "/api/v1/chores").json()[0]["status"] == "sent_back"

    # Again, approved: a weekly chore moves to next Tuesday at the same time, still open.
    sub2 = _req(kid, "POST", f"/api/v1/tasks/{task['id']}/submissions", json={}).json()
    _req(
        kid,
        "PUT",
        f"/api/v1/submissions/{sub2['id']}/photo",
        headers={"content-type": "application/octet-stream"},
        content=jpeg_with_gps(),
    )
    _req(owner, "POST", f"/api/v1/submissions/{sub2['id']}/review", json={"approve": True})
    after = _req(kid, "GET", "/api/v1/chores").json()[0]
    assert (after["status"], after["done"]) == (None, False)
    next_due = datetime.fromisoformat(after["due_at"])
    assert next_due > datetime.now(UTC)
    assert next_due.astimezone(UTC).weekday() in (1, 2)
    assert "chore_approved" in _kinds(kid)


def test_one_off_chores_and_who_can_mark_them(team: Team) -> None:
    owner, _, kid, pid, _ = team
    task = _task(owner, pid, "Cut the lawn")
    _assign(owner, task, assignee_id=kid.id)
    # Only the assignee marks it done; others (even the owner) can't.
    assert (
        _req(owner, "POST", f"/api/v1/tasks/{task['id']}/submissions", json={}).status_code == 403
    )
    assert _req(kid, "POST", f"/api/v1/tasks/{task['id']}/submissions", json={}).json()[
        "status"
    ] == ("approved")  # no proof asked: done at once
    assert _req(kid, "GET", "/api/v1/chores").json() == []
    tasks = _req(owner, "GET", f"/api/v1/projects/{pid}/tasks").json()
    assert [t["done"] for t in tasks if t["title"] == "Cut the lawn"] == [True]

    # A note proof needs a note; an unassigned task can't be "done" by a stranger.
    noted = _task(owner, pid, "Feed the cat")
    _assign(owner, noted, assignee_id=kid.id, proof="note")
    path = f"/api/v1/tasks/{noted['id']}/submissions"
    assert _req(kid, "POST", path, json={"note": " "}).status_code == 422
    assert _req(kid, "POST", path, json={"note": "Two scoops"}).json()["status"] == "pending"
    other = _task(owner, pid, "Not yours")
    assert _req(kid, "POST", f"/api/v1/tasks/{other['id']}/submissions", json={}).status_code == 404
    # An assignee must be an account on the server.
    nobody = "00000000-0000-7000-8000-000000000000"
    other = _req(owner, "GET", f"/api/v1/projects/{pid}/tasks").json()[-1]
    assert _assign(owner, other, assignee_id=nobody).status_code == 404


def test_reminders(team: Team) -> None:
    import asyncio

    owner, _, kid, pid, _ = team
    task = _task(owner, pid, "Water plants")
    due = datetime.now(UTC) - timedelta(hours=4)
    _assign(owner, task, assignee_id=kid.id, due_at=due.isoformat())

    async def run() -> tuple[int, int]:
        db = Database(_settings())
        try:
            return await chore_service.remind(db), await chore_service.remind(db)
        finally:
            await db.dispose()

    first, again = asyncio.run(run())
    assert (first, again) == (2, 0)  # "due", then (hours later) a reminder; once each
    assert {"chore_due", "chore_reminder"} <= set(_kinds(kid))

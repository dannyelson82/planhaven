"""Items a task needs, from the project's lists."""

from typing import Any

import pytest

from tests.db import team as setup
from tests.db.team import U

pytestmark = pytest.mark.db

team = setup.team  # the shared fixture: owner, viewer, stranger, project, note

type Team = tuple[U, U, U, str, str]


def _req(u: U, method: str, path: str, **kw: Any) -> Any:
    u._cookie()
    return u.client.request(method, path, headers={**u.h, **kw.pop("headers", {})}, **kw)


def test_task_needs(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    tid = owner.post(
        f"/api/v1/projects/{pid}/tasks", headers=owner.h, json={"title": "Change oil"}
    ).json()["id"]
    lid = owner.post(
        f"/api/v1/projects/{pid}/lists", headers=owner.h, json={"title": "Parts"}
    ).json()["id"]
    oil = owner.post(f"/api/v1/lists/{lid}/items", headers=owner.h, json={"text": "Oil"}).json()[
        "id"
    ]
    flt = owner.post(f"/api/v1/lists/{lid}/items", headers=owner.h, json={"text": "Filter"}).json()[
        "id"
    ]

    assert (
        _req(owner, "PUT", f"/api/v1/tasks/{tid}/needs", json={"item_ids": [oil, flt]}).status_code
        == 204
    )
    _req(owner, "PATCH", f"/api/v1/list-items/{oil}", json={"checked": True})
    needs = viewer.get(f"/api/v1/projects/{pid}/task-needs").json()
    assert {(n["text"], n["checked"]) for n in needs} == {("Oil", True), ("Filter", False)}
    assert all(n["task_id"] == tid and n["list_title"] == "Parts" for n in needs)

    # Viewers can't change it; strangers can't see it; items from another project are refused.
    assert (
        _req(viewer, "PUT", f"/api/v1/tasks/{tid}/needs", json={"item_ids": []}).status_code == 403
    )
    assert stranger.get(f"/api/v1/projects/{pid}/task-needs").status_code == 404
    other = owner.post("/api/v1/projects", headers=owner.h, json={"title": "Other"}).json()["id"]
    olist = owner.post(
        f"/api/v1/projects/{other}/lists", headers=owner.h, json={"title": "X"}
    ).json()["id"]
    elsewhere = owner.post(
        f"/api/v1/lists/{olist}/items", headers=owner.h, json={"text": "Y"}
    ).json()["id"]
    r = _req(owner, "PUT", f"/api/v1/tasks/{tid}/needs", json={"item_ids": [elsewhere]})
    assert r.status_code == 422

    # Deleting an item drops it from the task's needs.
    assert _req(owner, "DELETE", f"/api/v1/list-items/{flt}").status_code == 204
    assert [n["text"] for n in owner.get(f"/api/v1/projects/{pid}/task-needs").json()] == ["Oil"]

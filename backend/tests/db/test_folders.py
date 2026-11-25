"""Project folders, each person's own (ADR 0022)."""

from typing import Any

import pytest

from tests.db import team as setup
from tests.db.team import U

pytestmark = pytest.mark.db

team = setup.team

type Team = tuple[U, U, U, str, str]


def _folder(u: U, name: str, parent: str | None = None) -> dict[str, Any]:
    r = u.post("/api/v1/folders", headers=u.h, json={"name": name, "parent_id": parent})
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def _patch(u: U, folder_id: str, **body: Any) -> Any:
    u._cookie()
    return u.client.patch(f"/api/v1/folders/{folder_id}", headers=u.h, json=body)


def _file(u: U, pid: str, folder_id: str | None) -> int:
    u._cookie()
    status: int = u.client.put(
        f"/api/v1/projects/{pid}/folder", headers=u.h, json={"folder_id": folder_id}
    ).status_code
    return status


def _folder_of(u: U, pid: str) -> str | None:
    items = u.get("/api/v1/projects").json()["items"]
    value: str | None = next(p for p in items if p["id"] == pid)["folder_id"]
    return value


def test_each_person_files_projects_in_their_own_folders(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    cars = _folder(owner, "Cars")
    corolla = _folder(owner, "  Corolla  ", cars["id"])
    assert corolla["name"] == "Corolla"
    assert corolla["parent_id"] == cars["id"]
    assert _file(owner, pid, corolla["id"]) == 204
    assert _folder_of(owner, pid) == corolla["id"]
    assert owner.get(f"/api/v1/projects/{pid}").json()["folder_id"] == corolla["id"]
    listed = {f["name"]: f for f in owner.get("/api/v1/folders").json()}
    assert listed["Corolla"]["projects"] == 1
    assert listed["Cars"]["projects"] == 0

    # The viewer shares the project but not the folders.
    assert viewer.get("/api/v1/folders").json() == []
    assert _folder_of(viewer, pid) is None
    house = _folder(viewer, "House")
    assert _file(viewer, pid, house["id"]) == 204
    assert _folder_of(viewer, pid) == house["id"]
    assert _folder_of(owner, pid) == corolla["id"]
    # Nobody can use or change someone else's folders.
    assert _file(viewer, pid, corolla["id"]) == 404
    assert _patch(viewer, corolla["id"], name="Mine").status_code == 404
    viewer._cookie()
    assert (
        viewer.client.delete(f"/api/v1/folders/{corolla['id']}", headers=viewer.h).status_code
        == 404
    )
    # A project you can't see can't be filed.
    mine = _folder(stranger, "Stuff")
    assert _file(stranger, pid, mine["id"]) == 404

    assert _file(owner, pid, None) == 204
    assert _folder_of(owner, pid) is None


def test_folder_trees_stay_sound(team: Team) -> None:
    owner = team[0]
    a = _folder(owner, "A")
    b = _folder(owner, "B", a["id"])
    r = _patch(owner, a["id"], parent_id=b["id"])
    assert r.status_code == 400
    assert "inside itself" in r.json()["detail"]
    # At most 5 levels.
    parent = b["id"]
    for name in ("C", "D", "E"):
        parent = _folder(owner, name, parent)["id"]
    r = owner.post("/api/v1/folders", headers=owner.h, json={"name": "F", "parent_id": parent})
    assert r.status_code == 400
    assert "5 levels" in r.json()["detail"]
    # Rename and move to the top.
    moved = _patch(owner, b["id"], name="Bee", parent_id=None)
    assert moved.status_code == 200, moved.text
    assert moved.json()["parent_id"] is None
    assert moved.json()["name"] == "Bee"
    blank = owner.post("/api/v1/folders", headers=owner.h, json={"name": " "})
    assert blank.status_code == 400


def test_deleting_a_folder_keeps_what_was_in_it(team: Team) -> None:
    owner, _, _, pid, _ = team
    top = _folder(owner, "Top")
    middle = _folder(owner, "Middle", top["id"])
    inner = _folder(owner, "Inner", middle["id"])
    _file(owner, pid, middle["id"])
    owner._cookie()
    assert (
        owner.client.delete(f"/api/v1/folders/{middle['id']}", headers=owner.h).status_code == 204
    )
    folders = {f["id"]: f for f in owner.get("/api/v1/folders").json()}
    assert middle["id"] not in folders
    assert folders[inner["id"]]["parent_id"] == top["id"]
    assert _folder_of(owner, pid) == top["id"]
    # Deleting a top-level folder leaves its projects in no folder.
    owner._cookie()
    owner.client.delete(f"/api/v1/folders/{top['id']}", headers=owner.h)
    assert _folder_of(owner, pid) is None
    assert owner.get(f"/api/v1/projects/{pid}").status_code == 200

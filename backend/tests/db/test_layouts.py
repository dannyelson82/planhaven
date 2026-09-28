"""Each person's arrangement of a project page (tiles); members follow the owner's."""

from typing import Any

import pytest

from tests.db import team as setup
from tests.db.team import U

pytestmark = pytest.mark.db

team = setup.team

type Team = tuple[U, U, U, str, str]
GROUPS = ["tasks", "lists", "notes", "files", "money"]


def _put(u: U, pid: str, tiles: list[dict[str, Any]]) -> Any:
    u._cookie()
    return u.client.put(f"/api/v1/projects/{pid}/layout", headers=u.h, json={"tiles": tiles})


def _kinds(layout: dict[str, Any]) -> list[str]:
    return [t["kind"] if t["id"] is None else f"{t['kind']}:{t['id']}" for t in layout["tiles"]]


def test_tiles_per_person_following_the_owner(team: Team) -> None:
    owner, viewer, stranger, pid, nid = team
    default = owner.get(f"/api/v1/projects/{pid}/layout").json()
    assert default["source"] == "default"
    assert _kinds(default) == GROUPS
    assert {t["width"] for t in default["tiles"]} == {"full"}
    # The owner puts one note at the top, wide, with the notes group narrow beside it.
    # Repeats are dropped; groups left out are added at the end.
    r = _put(
        owner,
        pid,
        [
            {"kind": "note", "id": nid, "width": "wide"},
            {"kind": "notes", "width": "narrow"},
            {"kind": "note", "id": nid, "width": "full"},
        ],
    )
    assert r.status_code == 200, r.text
    arranged = [f"note:{nid}", "notes", "tasks", "lists", "files", "money"]
    assert r.json()["source"] == "mine"
    assert _kinds(r.json()) == arranged
    assert r.json()["tiles"][0]["width"] == "wide"
    # A member who hasn't arranged it sees the owner's arrangement.
    seen = viewer.get(f"/api/v1/projects/{pid}/layout").json()
    assert (seen["source"], _kinds(seen)) == ("owner", arranged)
    # Viewers can arrange their own view; it doesn't change the owner's.
    assert _put(viewer, pid, [{"kind": "money"}]).status_code == 200
    assert _kinds(viewer.get(f"/api/v1/projects/{pid}/layout").json())[0] == "money"
    assert _kinds(owner.get(f"/api/v1/projects/{pid}/layout").json()) == arranged
    # Reset: back to following the owner.
    viewer._cookie()
    back = viewer.client.delete(f"/api/v1/projects/{pid}/layout", headers=viewer.h).json()
    assert (back["source"], _kinds(back)) == ("owner", arranged)
    # Strangers see nothing; bad tiles are refused.
    assert stranger.get(f"/api/v1/projects/{pid}/layout").status_code == 404
    assert _put(stranger, pid, [{"kind": "tasks"}]).status_code == 404
    for bad in (
        [{"kind": "secrets"}],
        [{"kind": "note"}],  # a single note needs its id
        [{"kind": "tasks", "id": nid}],  # groups have none
        [{"kind": "tasks", "width": "huge"}],
        [{"kind": "tasks", "style": "x"}],
    ):
        assert _put(owner, pid, bad).status_code == 422, bad

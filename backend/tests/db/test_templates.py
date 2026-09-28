"""Templates: lists and task sets saved for later projects; private until shared."""

from typing import Any

import pytest

from tests.db import team as setup
from tests.db.team import U

pytestmark = pytest.mark.db

team = setup.team

type Team = tuple[U, U, U, str, str]


def _req(u: U, method: str, path: str, **kw: Any) -> Any:
    u._cookie()
    return u.client.request(method, path, headers={**u.h, **kw.pop("headers", {})}, **kw)


def test_save_use_share_and_delete_templates(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    lid = _req(
        owner, "POST", f"/api/v1/projects/{pid}/lists", json={"title": "Hardware", "kind": "parts"}
    ).json()["id"]
    for item in ({"text": "Hose clamps", "quantity": "4", "price_cents": 250}, {"text": "Rags"}):
        _req(owner, "POST", f"/api/v1/lists/{lid}/items", json=item)
    for title in ("Drain water lines", "Change oil"):
        _req(owner, "POST", f"/api/v1/projects/{pid}/tasks", json={"title": title})

    r = _req(owner, "POST", f"/api/v1/lists/{lid}/template", json={"name": "Boat parts"})
    assert r.status_code == 201, r.text
    parts = r.json()
    assert (parts["kind"], parts["list_kind"], parts["item_count"]) == ("list", "parts", 2)
    tasks = _req(
        owner, "POST", f"/api/v1/projects/{pid}/tasks/template", json={"name": "Winterize"}
    ).json()
    assert (tasks["kind"], tasks["item_count"]) == ("tasks", 2)
    detail = owner.get(f"/api/v1/templates/{parts['id']}").json()
    assert detail["items"][0]["text"] == "Hose clamps"
    assert detail["items"][0]["price_cents"] == 250

    # Private: a project member doesn't see them until shared.
    assert viewer.get("/api/v1/templates").json() == []
    assert viewer.get(f"/api/v1/templates/{parts['id']}").status_code == 404
    assert stranger.get(f"/api/v1/templates/{parts['id']}").status_code == 404

    # Using a template in a project: a new list with the items and prices; the tasks.
    used = _req(owner, "POST", f"/api/v1/templates/{parts['id']}/use", json={"project_id": pid})
    assert used.status_code == 200, used.text
    new_list = owner.get(f"/api/v1/lists/{used.json()['list_id']}").json()
    assert (new_list["title"], new_list["kind"]) == ("Boat parts", "parts")
    assert [(i["text"], i["price_cents"]) for i in new_list["items"]] == [
        ("Hose clamps", 250),
        ("Rags", None),
    ]
    _req(owner, "POST", f"/api/v1/templates/{tasks['id']}/use", json={"project_id": pid})
    titles = [t["title"] for t in owner.get(f"/api/v1/projects/{pid}/tasks").json()]
    assert titles.count("Change oil") == 2

    # Shared (as a viewer): they can use it in their own project, not change it.
    r = _req(
        owner,
        "POST",
        f"/api/v1/templates/{parts['id']}/members",
        json={"user_id": viewer.id, "role": "viewer"},
    )
    assert r.status_code == 201, r.text
    assert [t["name"] for t in viewer.get("/api/v1/templates").json()] == ["Boat parts"]
    mine = _req(viewer, "POST", "/api/v1/projects", json={"title": "Viewer's shed"}).json()["id"]
    use = _req(viewer, "POST", f"/api/v1/templates/{parts['id']}/use", json={"project_id": mine})
    assert use.status_code == 200
    # ...but not in a project where they can only view.
    use = _req(viewer, "POST", f"/api/v1/templates/{parts['id']}/use", json={"project_id": pid})
    assert use.status_code == 403
    rename = _req(
        viewer,
        "PATCH",
        f"/api/v1/templates/{parts['id']}",
        json={"name": "x"},
        headers={"if-match": f'"{parts["version"]}"'},
    )
    assert rename.status_code == 403
    assert _req(viewer, "DELETE", f"/api/v1/templates/{parts['id']}").status_code == 403
    assert _req(stranger, "DELETE", f"/api/v1/templates/{parts['id']}").status_code == 404

    # The owner renames it, removes an item, and deletes it (members and items go too).
    r = _req(
        owner,
        "PATCH",
        f"/api/v1/templates/{parts['id']}",
        json={"name": "Boat parts run"},
        headers={"if-match": f'"{parts["version"]}"'},
    )
    assert r.status_code == 200, r.text
    rags = owner.get(f"/api/v1/templates/{parts['id']}").json()["items"][1]
    assert _req(viewer, "DELETE", f"/api/v1/template-items/{rags['id']}").status_code == 403
    assert _req(owner, "DELETE", f"/api/v1/template-items/{rags['id']}").status_code == 204
    assert owner.get(f"/api/v1/templates/{parts['id']}").json()["item_count"] == 1
    assert _req(owner, "DELETE", f"/api/v1/templates/{parts['id']}").status_code == 204
    assert owner.get(f"/api/v1/templates/{parts['id']}").status_code == 404
    assert viewer.get("/api/v1/templates").json() == []
    # The list made from it stays.
    assert owner.get(f"/api/v1/lists/{new_list['id']}").status_code == 200


def test_an_empty_list_makes_no_template(team: Team) -> None:
    owner, _, _, pid, _ = team
    lid = _req(
        owner, "POST", f"/api/v1/projects/{pid}/lists", json={"title": "Empty", "kind": "shopping"}
    ).json()["id"]
    r = _req(owner, "POST", f"/api/v1/lists/{lid}/template", json={"name": "Nothing"})
    assert r.status_code == 422

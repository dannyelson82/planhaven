"""Lists and items: roles, check-off without conflicts, idempotent creates."""

import pytest

from app.db.database import Database
from tests.db.test_projects import User, _project, _share

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def test_lists_follow_project_roles(people: dict[str, User], db: Database) -> None:
    owner, viewer, stranger = people["owner"], people["viewer"], people["stranger"]
    pid = (await _project(owner))["id"]
    await _share(db, owner, str(pid), viewer, "viewer")
    created = await owner.client.post(
        f"/api/v1/projects/{pid}/lists",
        headers=owner.h,
        json={"title": "Hardware store", "kind": "shopping"},
    )
    assert created.status_code == 201
    lid = created.json()["id"]

    assert (await viewer.client.get(f"/api/v1/lists/{lid}")).status_code == 200
    assert (
        await viewer.client.post(
            f"/api/v1/lists/{lid}/items", headers=viewer.h, json={"text": "nails"}
        )
    ).status_code == 403
    assert (await stranger.client.get(f"/api/v1/lists/{lid}")).status_code == 404
    assert (await stranger.client.get(f"/api/v1/projects/{pid}/lists")).status_code == 404


async def test_items_add_check_and_counts(people: dict[str, User]) -> None:
    owner = people["owner"]
    pid = (await _project(owner))["id"]
    lid = (
        await owner.client.post(
            f"/api/v1/projects/{pid}/lists",
            headers=owner.h,
            json={"title": "Parts", "kind": "parts"},
        )
    ).json()["id"]
    a = (
        await owner.client.post(
            f"/api/v1/lists/{lid}/items",
            headers=owner.h,
            json={
                "text": "3/4 in Baltic birch 5x5",
                "quantity": "3",
                "unit": "sheets",
                "price_cents": 8999,
            },
        )
    ).json()
    await owner.client.post(
        f"/api/v1/lists/{lid}/items", headers=owner.h, json={"text": "Edge banding"}
    )

    # Checking off needs no version (it's a state, not an edit), even with a stale view.
    checked = await owner.client.patch(
        f"/api/v1/list-items/{a['id']}", headers=owner.h, json={"checked": True}
    )
    assert checked.status_code == 200
    assert checked.json()["checked"] is True
    again = await owner.client.patch(
        f"/api/v1/list-items/{a['id']}", headers=owner.h, json={"checked": True}
    )
    assert again.status_code == 200  # idempotent

    # Editing text needs If-Match.
    assert (
        await owner.client.patch(
            f"/api/v1/list-items/{a['id']}", headers=owner.h, json={"text": "x"}
        )
    ).status_code == 428
    stale = await owner.client.patch(
        f"/api/v1/list-items/{a['id']}",
        headers={**owner.h, "if-match": str(a["version"])},
        json={"text": "x"},
    )
    assert stale.status_code == 409

    body = (await owner.client.get(f"/api/v1/lists/{lid}")).json()
    assert (body["open_items"], body["total_items"]) == (1, 2)
    assert body["items"][0]["text"] == "Edge banding"  # open items first
    assert body["items"][1]["quantity"] == "3.000"


async def test_idempotent_create_for_offline_replay(people: dict[str, User]) -> None:
    owner = people["owner"]
    pid = (await _project(owner))["id"]
    lid = (
        await owner.client.post(
            f"/api/v1/projects/{pid}/lists", headers=owner.h, json={"title": "Groceries"}
        )
    ).json()["id"]
    headers = {**owner.h, "Idempotency-Key": "offline-0001-milk"}
    first = await owner.client.post(
        f"/api/v1/lists/{lid}/items", headers=headers, json={"text": "Milk"}
    )
    replay = await owner.client.post(
        f"/api/v1/lists/{lid}/items", headers=headers, json={"text": "Milk"}
    )
    assert first.json()["id"] == replay.json()["id"]
    items = (await owner.client.get(f"/api/v1/lists/{lid}")).json()["items"]
    assert [i["text"] for i in items] == ["Milk"]

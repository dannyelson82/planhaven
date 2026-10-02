"""List item details, saving when safe over a newer copy, pasting many items, and moving items
between lists (owner requests, 2026-10-02)."""

from typing import Any

import pytest

from app.db.database import Database
from tests.db.test_projects import User, _project, _share

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def _list(u: User, pid: object, title: str = "Inbox") -> str:
    r = await u.client.post(f"/api/v1/projects/{pid}/lists", headers=u.h, json={"title": title})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _item(u: User, lid: str, text: str = "Hose clamps") -> dict[str, Any]:
    r = await u.client.post(f"/api/v1/lists/{lid}/items", headers=u.h, json={"text": text})
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


async def _patch(u: User, item: dict[str, Any], body: dict[str, Any]) -> Any:
    return await u.client.patch(
        f"/api/v1/list-items/{item['id']}",
        headers={**u.h, "if-match": f'"{item["version"]}"'},
        json=body,
    )


async def test_notes_and_website(people: dict[str, User]) -> None:
    owner = people["owner"]
    lid = await _list(owner, (await _project(owner))["id"])
    item = await _item(owner, lid)
    assert (item["notes"], item["website"]) == ("", "")

    r = await _patch(owner, item, {"notes": "Stainless", "website": "https://example.com/c"})
    assert r.status_code == 200, r.text
    assert (r.json()["notes"], r.json()["website"]) == ("Stainless", "https://example.com/c")

    for bad in ("javascript:alert(1)", "example.com", "https://a b"):
        assert (await _patch(owner, r.json(), {"website": bad})).status_code == 422


async def test_merge_when_safe(people: dict[str, User]) -> None:
    """A save over a newer copy goes through when only other fields changed meanwhile."""
    owner = people["owner"]
    lid = await _list(owner, (await _project(owner))["id"])
    seen = await _item(owner, lid)  # what "this device" opened
    # Meanwhile, on another device: the notes change.
    other = await _patch(owner, seen, {"notes": "From the phone", "base": {"notes": ""}})
    assert other.status_code == 200

    # This device changes the name, from the old version: kept, and so are the notes.
    r = await _patch(owner, seen, {"text": "Clamps", "base": {"text": "Hose clamps"}})
    assert r.status_code == 200, r.text
    assert (r.json()["text"], r.json()["notes"]) == ("Clamps", "From the phone")

    # Changing the same field from the old version is a conflict...
    clash = await _patch(owner, seen, {"notes": "From the laptop", "base": {"notes": ""}})
    assert clash.status_code == 409
    # ...as is any stale save without a base (older clients), or a base that doesn't cover
    # every changed field.
    assert (await _patch(owner, seen, {"text": "Clips"})).status_code == 409
    partial = {"text": "Clips", "notes": "y", "base": {"text": "Clamps"}}
    assert (await _patch(owner, seen, partial)).status_code == 409
    # "Keep mine": saving with the newest version wins.
    latest = r.json()
    assert (await _patch(owner, latest, {"notes": "From the laptop"})).status_code == 200


async def test_task_merge_when_safe(people: dict[str, User]) -> None:
    owner = people["owner"]
    pid = (await _project(owner))["id"]
    task = (
        await owner.client.post(
            f"/api/v1/projects/{pid}/tasks", headers=owner.h, json={"title": "Oil"}
        )
    ).json()
    url = f"/api/v1/tasks/{task['id']}"
    h = {**owner.h, "if-match": f'"{task["version"]}"'}
    # Ticked on the phone, then notes saved on the laptop from the old version: both kept.
    assert (await owner.client.patch(url, headers=h, json={"done": True})).status_code == 200
    r = await owner.client.patch(url, headers=h, json={"notes": "5W-30", "base": {"notes": ""}})
    assert r.status_code == 200, r.text
    assert (r.json()["done"], r.json()["notes"]) == (True, "5W-30")
    # The same field changed on both: conflict.
    clash = await owner.client.patch(url, headers=h, json={"done": False, "base": {"done": False}})
    assert clash.status_code == 409


async def test_paste_many_items(people: dict[str, User], db: Database) -> None:
    owner, viewer = people["owner"], people["viewer"]
    pid = (await _project(owner))["id"]
    await _share(db, owner, str(pid), viewer, "viewer")
    lid = await _list(owner, pid)
    url = f"/api/v1/lists/{lid}/items/bulk"
    texts = ["Nails", "Screws", "Glue"]
    key = {**owner.h, "idempotency-key": "bulk-key-1"}
    r = await owner.client.post(url, headers=key, json={"texts": texts})
    assert (r.status_code, r.json()) == (201, {"count": 3})
    # Replayed (offline queue): not added twice.
    assert (await owner.client.post(url, headers=key, json={"texts": texts})).status_code == 201
    items = (await owner.client.get(f"/api/v1/lists/{lid}")).json()["items"]
    assert [i["text"] for i in items] == texts

    assert (
        await viewer.client.post(url, headers=viewer.h, json={"texts": ["x"]})
    ).status_code == 403
    assert (await owner.client.post(url, headers=owner.h, json={"texts": []})).status_code == 422
    too_many = {"texts": ["x"] * 201}
    assert (await owner.client.post(url, headers=owner.h, json=too_many)).status_code == 422


async def test_move_items_within_a_project(people: dict[str, User], db: Database) -> None:
    owner, viewer = people["owner"], people["viewer"]
    pid = (await _project(owner))["id"]
    await _share(db, owner, str(pid), viewer, "viewer")
    inbox, store = await _list(owner, pid), await _list(owner, pid, "Hardware store")
    a, b, c = [await _item(owner, inbox, t) for t in ("Nails", "Bread", "Screws")]
    await _item(owner, store, "Tape")

    url = f"/api/v1/lists/{inbox}/move-items"
    r = await owner.client.post(
        url, headers=owner.h, json={"item_ids": [c["id"], a["id"]], "to_list_id": store}
    )
    assert r.json() == {"count": 2}
    moved = (await owner.client.get(f"/api/v1/lists/{store}")).json()["items"]
    assert [i["text"] for i in moved] == ["Tape", "Nails", "Screws"]  # at the end, in order
    left = (await owner.client.get(f"/api/v1/lists/{inbox}")).json()["items"]
    assert [i["text"] for i in left] == ["Bread"]

    # Viewers can't; items of another list are left alone.
    body = {"item_ids": [b["id"]], "to_list_id": store}
    assert (await viewer.client.post(url, headers=viewer.h, json=body)).status_code == 403
    wrong = {"item_ids": [a["id"]], "to_list_id": inbox}
    assert (await owner.client.post(url, headers=owner.h, json=wrong)).json() == {"count": 0}

    # Never to another project's list, even one this person owns.
    elsewhere = await _list(owner, (await _project(owner))["id"])
    away = {"item_ids": [b["id"]], "to_list_id": elsewhere}
    assert (await owner.client.post(url, headers=owner.h, json=away)).status_code == 404
    # Nor to a list the person can't see.
    stranger = people["stranger"]
    theirs = await _list(stranger, (await _project(stranger))["id"])
    hidden = {"item_ids": [b["id"]], "to_list_id": theirs}
    assert (await owner.client.post(url, headers=owner.h, json=hidden)).status_code == 404

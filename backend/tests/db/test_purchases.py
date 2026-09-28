"""Purchases: a cost entry's store, receipt and item lines, some copied from a list."""

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


def _upload(u: U, pid: str, name: str) -> str:
    r = _req(
        u,
        "POST",
        f"/api/v1/projects/{pid}/attachments",
        params={"filename": name},
        content=b"%PDF-1.4\n%%EOF\n",
        headers={"content-type": "application/octet-stream"},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_a_purchase_with_receipt_and_items_from_a_list(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    lid = _req(
        owner, "POST", f"/api/v1/projects/{pid}/lists", json={"title": "Hardware", "kind": "parts"}
    ).json()["id"]
    clamps = _req(
        owner,
        "POST",
        f"/api/v1/lists/{lid}/items",
        json={"text": "Hose clamps", "quantity": "4", "price_cents": 250},
    ).json()
    cost = _req(
        owner,
        "POST",
        f"/api/v1/projects/{pid}/costs",
        json={"description": "Hardware run", "amount_cents": 1130},
    ).json()
    cid = cost["id"]
    detail = viewer.get(f"/api/v1/costs/{cid}").json()
    assert (detail["items"], detail["can_edit"], detail["store"]) == ([], False, "")

    # Items: one typed, one copied from the list with its estimated price; copying again
    # doesn't duplicate it.
    r = _req(
        owner,
        "POST",
        f"/api/v1/costs/{cid}/items",
        json={"items": [{"text": "Rags", "price_cents": 399}], "list_item_ids": [clamps["id"]]},
    )
    assert r.status_code == 201, r.text
    items = {i["text"]: i for i in r.json()}
    assert items["Hose clamps"]["price_cents"] == 250
    assert items["Hose clamps"]["list_item_id"] == clamps["id"]
    again = _req(
        owner, "POST", f"/api/v1/costs/{cid}/items", json={"list_item_ids": [clamps["id"]]}
    )
    assert len(again.json()) == 2

    # What was actually paid for the clamps.
    item = items["Hose clamps"]
    r = _req(
        owner,
        "PATCH",
        f"/api/v1/cost-items/{item['id']}",
        json={"price_cents": 199},
        headers={"if-match": f'"{item["version"]}"'},
    )
    assert r.status_code == 200, r.text
    stale = _req(
        owner,
        "PATCH",
        f"/api/v1/cost-items/{item['id']}",
        json={"price_cents": 1},
        headers={"if-match": f'"{item["version"]}"'},
    )
    assert stale.status_code == 409

    # Store and receipt (a file of this project only).
    receipt = _upload(owner, pid, "receipt.pdf")
    r = _req(
        owner,
        "PATCH",
        f"/api/v1/costs/{cid}",
        json={"store": "Harbour Hardware", "receipt_id": receipt},
        headers={"if-match": f'"{cost["version"]}"'},
    )
    assert r.status_code == 200, r.text
    listed = viewer.get(f"/api/v1/projects/{pid}/costs").json()
    assert listed[0]["store"] == "Harbour Hardware"
    assert (listed[0]["receipt_name"], listed[0]["item_count"]) == ("receipt.pdf", 2)
    other = _req(owner, "POST", "/api/v1/projects", json={"title": "Other"}).json()["id"]
    elsewhere = _upload(owner, other, "not-this-one.pdf")
    r = _req(
        owner,
        "PATCH",
        f"/api/v1/costs/{cid}",
        json={"receipt_id": elsewhere},
        headers={"if-match": f'"{r.json()["version"]}"'},
    )
    assert r.status_code == 422
    # A list item from another project isn't copied.
    other_list = _req(
        owner, "POST", f"/api/v1/projects/{other}/lists", json={"title": "X", "kind": "parts"}
    ).json()["id"]
    foreign = _req(owner, "POST", f"/api/v1/lists/{other_list}/items", json={"text": "X"}).json()
    r = _req(owner, "POST", f"/api/v1/costs/{cid}/items", json={"list_item_ids": [foreign["id"]]})
    assert len(r.json()) == 2

    # Viewers read, can't change; strangers see nothing; empty fields are refused.
    assert (
        _req(
            viewer,
            "PATCH",
            f"/api/v1/costs/{cid}",
            json={"store": "x"},
            headers={"if-match": '"1"'},
        ).status_code
        == 403
    )
    add = {"items": [{"text": "x"}]}
    assert _req(viewer, "POST", f"/api/v1/costs/{cid}/items", json=add).status_code == 403
    assert _req(viewer, "DELETE", f"/api/v1/cost-items/{item['id']}").status_code == 403
    assert stranger.get(f"/api/v1/costs/{cid}").status_code == 404
    assert _req(stranger, "DELETE", f"/api/v1/cost-items/{item['id']}").status_code == 404
    bad = _req(owner, "PATCH", f"/api/v1/costs/{cid}", json={"description": None})
    assert bad.status_code == 422
    assert (
        _req(
            owner, "POST", f"/api/v1/costs/{cid}/items", json={"items": [{"text": ""}]}
        ).status_code
        == 422
    )

    assert _req(owner, "DELETE", f"/api/v1/cost-items/{item['id']}").status_code == 204
    assert [i["text"] for i in owner.get(f"/api/v1/costs/{cid}").json()["items"]] == ["Rags"]

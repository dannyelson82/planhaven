"""Estimated prices on list items: list totals, and what's still to get."""

import pytest

from tests.db import team as setup
from tests.db.team import U

pytestmark = pytest.mark.db

team = setup.team

type Team = tuple[U, U, U, str, str]


def test_lists_add_up_estimated_prices(team: Team) -> None:
    owner, viewer, _, pid, _ = team
    lid = owner.post(
        f"/api/v1/projects/{pid}/lists", headers=owner.h, json={"title": "Parts", "kind": "parts"}
    ).json()["id"]
    empty = owner.get(f"/api/v1/lists/{lid}").json()
    assert (empty["estimated_cents"], empty["remaining_cents"]) == (None, None)
    items = [
        {"text": "Impeller", "price_cents": 4599},  # no quantity: counts once
        {"text": "Hose clamps", "quantity": "4", "price_cents": 250},
        {"text": "Rags"},  # no price: left out
    ]
    ids = [
        owner.post(f"/api/v1/lists/{lid}/items", headers=owner.h, json=item).json()["id"]
        for item in items
    ]
    listed = viewer.get(f"/api/v1/projects/{pid}/lists").json()
    parts = next(x for x in listed if x["id"] == lid)
    assert (parts["estimated_cents"], parts["remaining_cents"]) == (5599, 5599)
    owner._cookie()
    owner.client.patch(f"/api/v1/list-items/{ids[0]}", headers=owner.h, json={"checked": True})
    after = owner.get(f"/api/v1/lists/{lid}").json()
    assert (after["estimated_cents"], after["remaining_cents"]) == (5599, 1000)


def test_suggestions_while_typing_an_item(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    lid = owner.post(
        f"/api/v1/projects/{pid}/lists", headers=owner.h, json={"title": "Shop", "kind": "shopping"}
    ).json()["id"]
    for item in (
        {"text": "Hose clamps", "quantity": "4", "price_cents": 250},
        {"text": "Garden hose", "price_cents": 2999},
        {"text": "100% silicone"},
        {"text": "Rope"},
    ):
        owner.post(f"/api/v1/lists/{lid}/items", headers=owner.h, json=item)

    def names(u: U, q: str) -> list[str]:
        r = u.get("/api/v1/list-item-suggestions", params={"q": q})
        assert r.status_code == 200, r.text
        return [s["text"] for s in r.json()]

    # Starting with the words comes first; the last quantity and price come along.
    assert names(owner, "hose") == ["Hose clamps", "Garden hose"]
    first = owner.get("/api/v1/list-item-suggestions", params={"q": "hose"}).json()[0]
    assert (first["quantity"], first["price_cents"]) == ("4.000", 250)
    # Members see items of lists they can see; others don't.
    assert names(viewer, "rope") == ["Rope"]
    assert names(stranger, "rope") == []
    # Typed % and _ are plain characters, not wildcards.
    assert names(owner, "%") == ["100% silicone"]
    assert names(owner, "_") == []
    assert owner.get("/api/v1/list-item-suggestions", params={"q": ""}).status_code == 422

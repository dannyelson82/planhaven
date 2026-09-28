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

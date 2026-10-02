"""The welcome tour and "What's new" state: once per person, never moving back."""

import pytest

from tests.db.test_projects import User

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def test_tour_and_whats_new(people: dict[str, User]) -> None:
    ann, bob = people["owner"], people["viewer"]
    url = "/api/v1/onboarding"
    first = (await ann.client.get(url)).json()
    assert (first["welcome_done"], first["whats_new_seen"]) == (False, None)
    assert first["member_since"]  # for "What's new since you joined"

    r = await ann.client.put(
        url, headers=ann.h, json={"welcome_done": True, "whats_new_seen": "0.3.2"}
    )
    assert (r.json()["welcome_done"], r.json()["whats_new_seen"]) == (True, "0.3.2")
    # An older version (a device still on the previous release) doesn't move it back.
    r = await ann.client.put(url, headers=ann.h, json={"whats_new_seen": "0.3.1"})
    assert r.json()["whats_new_seen"] == "0.3.2"
    r = await ann.client.put(url, headers=ann.h, json={"whats_new_seen": "0.10.0"})
    assert r.json()["whats_new_seen"] == "0.10.0"
    assert (
        await ann.client.put(url, headers=ann.h, json={"whats_new_seen": "1.2"})
    ).status_code == 422

    # Bob's is his own.
    bobs = (await bob.client.get(url)).json()
    assert (bobs["welcome_done"], bobs["whats_new_seen"]) == (False, None)

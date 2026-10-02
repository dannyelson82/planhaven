"""Asset service (readings, schedules, records), suppliers on list items, and archived notes
(maintainer's testing notes, 2026-10-02)."""

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


def _boat_shared_with_viewer(owner: U, viewer: U) -> str:
    boat = owner.post("/api/v1/assets", headers=owner.h, json={"name": "Boat", "kind": "boat"})
    aid = str(boat.json()["id"])
    r = owner.post(
        f"/api/v1/assets/{aid}/members",
        headers=owner.h,
        json={"user_id": viewer.id, "role": "viewer"},
    )
    assert r.status_code == 201, r.text
    return aid


def test_service_schedules_records_and_due(team: Team) -> None:
    owner, viewer, stranger, _, _ = team
    aid = _boat_shared_with_viewer(owner, viewer)
    base = f"/api/v1/assets/{aid}"

    assert _req(owner, "PUT", f"{base}/distance-unit", json={"unit": "mi"}).status_code == 204
    r = _req(owner, "POST", f"{base}/readings", json={"read_on": "2026-09-01", "hours": "410"})
    assert r.status_code == 204
    # A reading needs a value; a schedule needs an interval.
    assert (
        _req(owner, "POST", f"{base}/readings", json={"read_on": "2026-09-01"}).status_code == 422
    )
    no_interval = {"name": "Impeller"}
    assert _req(owner, "POST", f"{base}/service-schedules", json=no_interval).status_code == 422

    oil = _req(
        owner,
        "POST",
        f"{base}/service-schedules",
        json={"name": "Engine oil", "every_hours": "100", "every_months": 12},
    ).json()
    view = _req(viewer, "GET", f"{base}/service").json()
    assert (view["distance_unit"], view["hours"], view["can_edit"]) == ("mi", "410.0", False)
    assert view["schedules"][0]["status"] == "unknown"  # never recorded yet

    # Done at 320 hours: due at 420; the meter is at 410, within the last tenth.
    record = {"schedule_id": oil["id"], "done_on": "2026-08-01", "hours": "320", "cost_cents": 8999}
    r = _req(owner, "POST", f"{base}/service-records", json=record)
    assert (r.status_code, r.json()["title"]) == (201, "Engine oil")
    s = _req(owner, "GET", f"{base}/service").json()["schedules"][0]
    assert (s["status"], s["due_hours"], s["last_done_on"]) == ("soon", "420.0", "2026-08-01")

    # Viewers and strangers can't change anything; strangers can't see it at all.
    assert (
        _req(
            viewer, "POST", f"{base}/readings", json={"read_on": "2026-09-02", "hours": "1"}
        ).status_code
        == 403
    )
    assert _req(viewer, "DELETE", f"/api/v1/service-schedules/{oil['id']}").status_code == 403
    assert _req(stranger, "GET", f"{base}/service").status_code == 404
    hidden = {"name": "x", "every_months": 1}
    assert _req(stranger, "POST", f"{base}/service-schedules", json=hidden).status_code == 404

    # A record can't name another asset's schedule.
    other = owner.post("/api/v1/assets", headers=owner.h, json={"name": "Car", "kind": "vehicle"})
    cross = {"schedule_id": oil["id"], "done_on": "2026-08-01"}
    path = f"/api/v1/assets/{other.json()['id']}/service-records"
    assert _req(owner, "POST", path, json=cross).status_code == 404

    # Edit the schedule (If-Match), then delete it; its records stay as history.
    put = _req(
        owner,
        "PUT",
        f"/api/v1/service-schedules/{oil['id']}",
        headers={"if-match": f'"{oil["version"]}"'},
        json={"name": "Engine oil", "every_hours": "50"},
    )
    assert put.status_code == 200, put.text
    assert _req(owner, "DELETE", f"/api/v1/service-schedules/{oil['id']}").status_code == 204
    after = _req(owner, "GET", f"{base}/service").json()
    assert after["schedules"] == []
    assert [x["title"] for x in after["records"]] == ["Engine oil"]


def test_supplier_on_list_items(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    lid = owner.post(
        f"/api/v1/projects/{pid}/lists", headers=owner.h, json={"title": "Parts", "kind": "parts"}
    ).json()["id"]
    item = owner.post(f"/api/v1/lists/{lid}/items", headers=owner.h, json={"text": "Belt"}).json()
    supplier = owner.post(
        "/api/v1/contacts", headers=owner.h, json={"name": "Marine Depot", "kind": "supplier"}
    ).json()

    r = _req(
        owner,
        "PATCH",
        f"/api/v1/list-items/{item['id']}",
        headers={"if-match": f'"{item["version"]}"'},
        json={"supplier_id": supplier["id"], "price_cents": 2499},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["supplier_name"], r.json()["price_cents"]) == ("Marine Depot", 2499)

    # The viewer is a project member but can't see the owner's supplier: the item shows
    # without it.
    listed = viewer.get(f"/api/v1/lists/{lid}").json()["items"]
    assert (listed[0]["supplier_id"], listed[0]["supplier_name"]) == (None, None)

    # Nobody can name a supplier they can't see.
    theirs = stranger.post(
        "/api/v1/contacts", headers=stranger.h, json={"name": "Secret", "kind": "supplier"}
    ).json()
    latest = r.json()
    bad = _req(
        owner,
        "PATCH",
        f"/api/v1/list-items/{item['id']}",
        headers={"if-match": f'"{latest["version"]}"'},
        json={"supplier_id": theirs["id"]},
    )
    assert bad.status_code == 404


def test_archived_notes(team: Team) -> None:
    owner, viewer, _, pid, nid = team
    assert (
        _req(viewer, "POST", f"/api/v1/notes/{nid}/archive", json={"archived": True}).status_code
        == 403
    )
    before = owner.get(f"/api/v1/notes/{nid}").json()
    assert (
        _req(owner, "POST", f"/api/v1/notes/{nid}/archive", json={"archived": True}).status_code
        == 204
    )

    assert nid not in [n["id"] for n in owner.get(f"/api/v1/projects/{pid}/notes").json()]
    assert nid not in [c["note_id"] for c in owner.get(f"/api/v1/projects/{pid}/note-cards").json()]
    archived = owner.get(f"/api/v1/projects/{pid}/notes", params={"archived": "true"}).json()
    assert [(n["id"], n["archived"]) for n in archived] == [(nid, True)]
    # Archiving isn't an edit: an editor open since before can still save.
    assert owner.get(f"/api/v1/notes/{nid}").json()["version"] == before["version"]

    assert (
        _req(owner, "POST", f"/api/v1/notes/{nid}/archive", json={"archived": False}).status_code
        == 204
    )
    assert nid in [n["id"] for n in owner.get(f"/api/v1/projects/{pid}/notes").json()]

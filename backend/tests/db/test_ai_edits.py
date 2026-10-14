"""AI apps editing and deleting (ADR 0020): every edit and delete is undoable, deletes go to the
Trash, members only within limits, and errors say why (for people building with AI apps)."""

from typing import Any

import pytest

from tests.db import team as setup
from tests.db.team import U
from tests.db.test_ai import _connect, _rpc

pytestmark = pytest.mark.db

team = setup.team  # owner, viewer, stranger, project, note

type Team = tuple[U, U, U, str, str]


def _call(u: U, token: str, name: str, /, **args: Any) -> dict[str, Any]:
    r = _rpc(u, token, "tools/call", {"name": name, "arguments": args})
    assert r.status_code == 200, r.text
    result: dict[str, Any] = r.json()["result"]
    return result


def _ok(u: U, token: str, name: str, /, **args: Any) -> dict[str, Any]:
    result = _call(u, token, name, **args)
    assert result["isError"] is False, result
    body: dict[str, Any] = result["structuredContent"]
    return body


def _err(u: U, token: str, name: str, /, **args: Any) -> dict[str, Any]:
    import json

    result = _call(u, token, name, **args)
    assert result["isError"] is True, result
    body: dict[str, Any] = json.loads(result["content"][0]["text"])
    return body


def _project(u: U, token: str, pid: str) -> dict[str, Any]:
    return _ok(u, token, "planhaven_get_project", project_id=pid)


def _undo(u: U, change_id: str) -> int:
    u._cookie()
    status: int = u.client.post(f"/api/v1/ai/changes/{change_id}/undo", headers=u.h).status_code
    return status


def test_edit_delete_and_undo_project_content(team: Team) -> None:
    owner, _, _, pid, _ = team
    t = _connect(owner, mode="apply")["access_token"]

    # Lists and items: add, edit, tick off, move, delete; each undone.
    shop = _ok(owner, t, "planhaven_add_list", project_id=pid, title="Shop", kind="shopping")
    parts = _ok(owner, t, "planhaven_add_list", project_id=pid, title="Parts", kind="parts")
    added = _ok(
        owner,
        t,
        "planhaven_add_list_items",
        list_id=shop["list_id"],
        items=[{"text": "Oil", "quantity": 2}, {"text": "Filter"}],
    )
    oil, filt = added["item_ids"]
    edit = _ok(owner, t, "planhaven_update_list_item", item_id=oil, text="5W-30 oil", done=True)
    _ok(
        owner,
        t,
        "planhaven_move_list_items",
        list_id=shop["list_id"],
        item_ids=[filt],
        to_list_id=parts["list_id"],
    )
    lists = {lst["title"]: lst for lst in _project(owner, t, pid)["lists"]}
    assert lists["Shop"]["items"][0] | {"id": oil} == {
        "id": oil,
        "text": "5W-30 oil",
        "quantity": "2",
        "notes": "",
        "done": True,
    }
    assert [i["id"] for i in lists["Parts"]["items"]] == [filt]
    assert _undo(owner, edit["change_id"]) == 204
    lists = {lst["title"]: lst for lst in _project(owner, t, pid)["lists"]}
    assert lists["Shop"]["items"][0]["text"] == "Oil"
    assert lists["Shop"]["items"][0]["done"] is False

    gone = _ok(owner, t, "planhaven_delete", kind="list_item", id=filt)
    assert gone["in_trash"] is True
    assert _project(owner, t, pid)["lists"][1]["items"] == []
    assert _undo(owner, gone["change_id"]) == 204
    lists = {lst["title"]: lst for lst in _project(owner, t, pid)["lists"]}
    assert [i["id"] for i in lists["Parts"]["items"]] == [filt]

    # Tasks: edit, clear the due date, un-complete, delete; undo restores.
    task_id = _ok(
        owner,
        t,
        "planhaven_add_tasks",
        project_id=pid,
        tasks=[{"title": "Change oil", "due_date": "2026-11-01"}],
    )["task_ids"][0]
    _ok(owner, t, "planhaven_complete_task", task_id=task_id)
    edit = _ok(
        owner,
        t,
        "planhaven_update_task",
        task_id=task_id,
        title="Change the oil",
        due_date=None,
        done=False,
    )
    task = next(x for x in _project(owner, t, pid)["tasks"] if x["id"] == task_id)
    assert (task["title"], task["due"], task["done"]) == ("Change the oil", None, False)
    assert _undo(owner, edit["change_id"]) == 204
    task = next(x for x in _project(owner, t, pid)["tasks"] if x["id"] == task_id)
    assert task["title"] == "Change oil"
    assert task["due"].startswith("2026-11-01")
    assert task["done"] is True

    gone = _ok(owner, t, "planhaven_delete", kind="task", id=task_id)
    assert "to the Trash" in gone["summary"]
    assert all(x["id"] != task_id for x in _project(owner, t, pid)["tasks"])
    owner._cookie()
    trash = owner.client.get("/api/v1/trash").json()
    assert any(row["id"] == task_id for row in trash)
    assert _undo(owner, gone["change_id"]) == 204
    assert any(x["id"] == task_id for x in _project(owner, t, pid)["tasks"])

    # Notes: replace the text and archive; undo puts both back.
    note_id = _ok(owner, t, "planhaven_add_note", project_id=pid, title="Plan", text="first")[
        "note_id"
    ]
    edit = _ok(owner, t, "planhaven_update_note", note_id=note_id, text="second", archived=True)
    note = next(n for n in _project(owner, t, pid)["notes"] if n["id"] == note_id)
    assert note["archived"] is True
    assert "second" in note["text"]
    assert _undo(owner, edit["change_id"]) == 204
    note = next(n for n in _project(owner, t, pid)["notes"] if n["id"] == note_id)
    assert note["archived"] is False
    assert "first" in note["text"]

    # A whole project: trashed with everything in it, and back.
    gone = _ok(owner, t, "planhaven_delete", kind="project", id=pid)
    assert _ok(owner, t, "planhaven_list_projects")["projects"] == []
    assert _undo(owner, gone["change_id"]) == 204
    assert [p["id"] for p in _ok(owner, t, "planhaven_list_projects")["projects"]] == [pid]
    assert any(x["id"] == task_id for x in _project(owner, t, pid)["tasks"])


def test_undo_says_when_it_cannot(team: Team) -> None:
    owner, _, _, pid, _ = team
    t = _connect(owner, mode="apply")["access_token"]
    task_id = _ok(owner, t, "planhaven_add_tasks", project_id=pid, tasks=[{"title": "x"}])[
        "task_ids"
    ][0]
    gone = _ok(owner, t, "planhaven_delete", kind="task", id=task_id)
    owner._cookie()
    r = owner.client.post(f"/api/v1/trash/task/{task_id}/restore", headers=owner.h)
    assert r.status_code == 204
    owner._cookie()
    r = owner.client.post(f"/api/v1/ai/changes/{gone['change_id']}/undo", headers=owner.h)
    assert r.status_code == 409
    assert "can't be brought back" in r.json()["detail"]


def test_quotes_costs_contacts_and_assets(team: Team) -> None:
    owner, _, _, pid, _ = team
    t = _connect(owner, mode="apply")["access_token"]

    contact = _ok(
        owner,
        t,
        "planhaven_add_contact",
        name="Dave",
        company="Dave's Garage",
        website="https://garage.example.com",
    )["contact_id"]
    assert (
        _err(owner, t, "planhaven_add_contact", name="x", website="ftp://x")["field"] == "website"
    )
    quote = _ok(
        owner,
        t,
        "planhaven_add_quote",
        project_id=pid,
        title="Service",
        contact_id=contact,
        amount=249.5,
    )["quote_id"]
    edit = _ok(owner, t, "planhaven_update_quote", quote_id=quote, status="accepted")
    cost = _ok(
        owner,
        t,
        "planhaven_add_cost",
        project_id=pid,
        description="Service",
        amount=249.5,
        quote_id=quote,
    )["cost_id"]
    cost_edit = _ok(owner, t, "planhaven_update_cost", cost_id=cost, amount=260)
    seen = _project(owner, t, pid)
    assert seen["quotes"][0]["status"] == "accepted"
    assert seen["quotes"][0]["contact"] == "Dave"
    assert seen["costs"][0]["amount"] == "260.00"
    assert _undo(owner, cost_edit["change_id"]) == 204
    assert _undo(owner, edit["change_id"]) == 204
    seen = _project(owner, t, pid)
    assert seen["costs"][0]["amount"] == "249.50"
    assert seen["quotes"][0]["status"] == "requested"
    contacts = _ok(owner, t, "planhaven_list_contacts")["contacts"]
    assert contacts[0]["company"] == "Dave's Garage"

    asset = _ok(
        owner,
        t,
        "planhaven_add_asset",
        name="Van",
        kind="vehicle",
        details=[{"label": "Plate", "value": "AB12 CDE"}],
    )["asset_id"]
    _ok(owner, t, "planhaven_update_asset", asset_id=asset, notes="Diesel")
    reading = _ok(
        owner,
        t,
        "planhaven_add_asset_reading",
        asset_id=asset,
        read_on="2026-10-01",
        distance=120500,
    )["reading_id"]
    schedule = _ok(
        owner,
        t,
        "planhaven_add_service_schedule",
        asset_id=asset,
        name="Oil change",
        every_distance=15000,
        every_months=12,
    )["schedule_id"]
    _ok(
        owner,
        t,
        "planhaven_add_service_record",
        asset_id=asset,
        schedule_id=schedule,
        done_on="2026-10-02",
        distance=120510,
        cost=89.99,
    )
    view = _ok(owner, t, "planhaven_get_asset", asset_id=asset)
    assert view["asset"]["notes"] == "Diesel"
    assert view["asset"]["details"] == [{"label": "Plate", "value": "AB12 CDE"}]
    assert view["readings"][0]["distance"] == "120500"
    assert view["service_schedules"][0]["last_done"] == "2026-10-02"

    # A deleted reading comes back on undo; a deleted schedule is restored.
    gone = _ok(owner, t, "planhaven_delete", kind="reading", id=reading)
    assert gone["in_trash"] is False
    assert _ok(owner, t, "planhaven_get_asset", asset_id=asset)["readings"] == []
    assert _undo(owner, gone["change_id"]) == 204
    assert len(_ok(owner, t, "planhaven_get_asset", asset_id=asset)["readings"]) == 1
    gone = _ok(owner, t, "planhaven_delete", kind="service_schedule", id=schedule)
    assert _ok(owner, t, "planhaven_get_asset", asset_id=asset)["service_schedules"] == []
    assert _undo(owner, gone["change_id"]) == 204
    assert len(_ok(owner, t, "planhaven_get_asset", asset_id=asset)["service_schedules"]) == 1

    gone = _ok(owner, t, "planhaven_delete", kind="contact", id=contact)
    assert _ok(owner, t, "planhaven_list_contacts")["contacts"] == []
    assert _undo(owner, gone["change_id"]) == 204
    assert len(_ok(owner, t, "planhaven_list_contacts")["contacts"]) == 1


def test_members_within_limits(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    t = _connect(owner, mode="apply")["access_token"]
    people = {p["name"]: p["user_id"] for p in _ok(owner, t, "planhaven_list_people")["people"]}
    assert set(people) == {"viewer", "stranger"}  # not the person themselves; no emails

    # No fresh second factor from an AI app's connection (it gave one when connecting).
    shared = _ok(
        owner, t, "planhaven_set_member", kind="project", id=pid, user_id=stranger.id, role="editor"
    )
    assert shared["status"] == "done"
    stranger._cookie()
    assert stranger.client.get(f"/api/v1/projects/{pid}").status_code == 200
    # Undoing it is the person's own sharing change: their session's step-up rules apply.
    assert _undo(owner, shared["change_id"]) == 204
    stranger._cookie()
    assert stranger.client.get(f"/api/v1/projects/{pid}").status_code == 404

    # Never the person's own access, never owners.
    own = _err(
        owner, t, "planhaven_set_member", kind="project", id=pid, user_id=owner.id, role="viewer"
    )
    assert own["code"] == "forbidden"
    owner_role = _err(
        owner, t, "planhaven_set_member", kind="project", id=pid, user_id=viewer.id, role="owner"
    )
    assert owner_role["code"] == "invalid_argument"

    # A viewer's AI app can't share what the viewer can't.
    vt = _connect(viewer, mode="apply")["access_token"]
    refused = _err(
        viewer,
        vt,
        "planhaven_set_member",
        kind="project",
        id=pid,
        user_id=stranger.id,
        role="viewer",
    )
    assert refused["code"] == "forbidden"
    assert _err(viewer, vt, "planhaven_delete", kind="project", id=pid)["code"] == "forbidden"


def test_connection_info_and_error_codes(team: Team) -> None:
    owner, _, _, pid, _ = team
    t = _connect(owner, mode="approve")["access_token"]
    info = _ok(owner, t, "planhaven_connection_info")
    assert info["access"] == "read and write"
    assert info["write_mode"].startswith("approve first")
    assert "planhaven_delete" in info["tools"]
    assert "not_found" in info["error_codes"]

    tools = {x["name"]: x for x in _rpc(owner, t, "tools/list").json()["result"]["tools"]}
    assert tools["planhaven_delete"]["annotations"]["destructiveHint"] is True
    assert tools["planhaven_update_task"]["annotations"]["destructiveHint"] is False

    bad = _err(owner, t, "planhaven_add_tasks", project_id=pid, tasks=[{"title": ""}])
    assert (bad["code"], bad["field"], bad["tool"]) == (
        "invalid_argument",
        "title",
        "planhaven_add_tasks",
    )
    assert bad["hint"]
    missing = _err(
        owner, t, "planhaven_delete", kind="task", id="00000000-0000-7000-8000-000000000000"
    )
    assert missing["code"] == "not_found"

    # Approve first: a delete waits like any other change.
    waiting = _ok(owner, t, "planhaven_delete", kind="project", id=pid)
    assert waiting["status"] == "waiting_for_approval"
    assert len(_ok(owner, t, "planhaven_list_projects")["projects"]) == 1

    read_only = _connect(owner, scope="read")["access_token"]
    assert _err(owner, read_only, "planhaven_delete", kind="project", id=pid)["code"] == (
        "read_only"
    )


def test_local_ai_only_cannot_be_changed_or_deleted(team: Team) -> None:
    owner, _, _, pid, _ = team
    t = _connect(owner, mode="apply")["access_token"]
    task_id = _ok(owner, t, "planhaven_add_tasks", project_id=pid, tasks=[{"title": "x"}])[
        "task_ids"
    ][0]
    owner._cookie()
    version = owner.client.get(f"/api/v1/projects/{pid}").json()["version"]
    r = owner.client.patch(
        f"/api/v1/projects/{pid}",
        headers={**owner.h, "if-match": f'"{version}"'},
        json={"local_ai_only": True},
    )
    assert r.status_code == 200, r.text
    assert _err(owner, t, "planhaven_delete", kind="project", id=pid)["code"] == "not_found"
    assert _err(owner, t, "planhaven_delete", kind="task", id=task_id)["code"] == "not_found"
    assert _err(owner, t, "planhaven_update_task", task_id=task_id, title="y")["code"] == (
        "not_found"
    )

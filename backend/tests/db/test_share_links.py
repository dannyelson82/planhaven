"""Share links (ADR 0015): a guest without an account gets exactly what the link was given,
checked by the app and again, item by item, by the database."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.db.database import OWNER_ROLE, Database
from app.services import note_content
from tests.db import team as setup
from tests.db.conftest import _settings
from tests.db.team import U
from tests.test_files import jpeg_with_gps

pytestmark = pytest.mark.db

team = setup.team

type Team = tuple[U, U, U, str, str]
SHARE = "__Host-planhaven_share"


def _req(u: U, method: str, path: str, **kw: Any) -> Any:
    u._cookie()
    return u.client.request(method, path, headers={**u.h, **kw.pop("headers", {})}, **kw)


class Guest:
    """Someone with the link: no account, only the link session cookie."""

    def __init__(self, u: U) -> None:
        self.client = u.client
        self.cookie = ""

    def open(self, url: str, name: str = "Dave", pin: str | None = None) -> Any:
        self.client.cookies.clear()
        token = url.split("#", 1)[1]
        r = self.client.post("/api/v1/share/open", json={"token": token, "name": name, "pin": pin})
        self.cookie = r.cookies.get(SHARE, "") or self.cookie
        return r

    def req(self, method: str, path: str, **kw: Any) -> Any:
        self.client.cookies.clear()
        if self.cookie:
            self.client.cookies.set(SHARE, self.cookie)
        return self.client.request(method, path, **kw)


def _project(owner: U, pid: str) -> dict[str, Any]:
    tasks = [
        _req(owner, "POST", f"/api/v1/projects/{pid}/tasks", json={"title": t}).json()["id"]
        for t in ("Change oil", "Private task")
    ]
    notes = [
        _req(owner, "POST", f"/api/v1/projects/{pid}/notes", json={"title": t}).json()["id"]
        for t in ("Instructions", "Service notes", "Private note")
    ]
    lists = [
        _req(
            owner, "POST", f"/api/v1/projects/{pid}/lists", json={"title": t, "kind": "parts"}
        ).json()["id"]
        for t in ("Parts", "Private list")
    ]
    items = [
        _req(owner, "POST", f"/api/v1/lists/{lid}/items", json={"text": f"Item in {n}"}).json()[
            "id"
        ]
        for n, lid in (("parts", lists[0]), ("private", lists[1]))
    ]
    return {"tasks": tasks, "notes": notes, "lists": lists, "items": items}


def _make(owner: U, pid: str, things: dict[str, Any], **extra: Any) -> Any:
    body = {
        "name": "Dave's Garage",
        "tasks_view": "chosen",
        "task_ids": [things["tasks"][0]],
        "tasks_tick": True,
        "note_ids": [things["notes"][0]],
        "append_note_id": things["notes"][1],
        "list_ids": [things["lists"][0]],
        "lists_tick": True,
        "files_view": True,
        "files_add": True,
        **extra,
    }
    return _req(owner, "POST", f"/api/v1/projects/{pid}/share-links", json=body)


def test_a_guest_gets_exactly_what_the_link_was_given(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    things = _project(owner, pid)
    r = _make(owner, pid, things)
    assert r.status_code == 201, r.text
    link = r.json()
    assert "/s#phv_shr_" in link["url"]
    assert link["pin"] is None  # off by default
    # Viewers can't make links; strangers don't see the project.
    assert _make(viewer, pid, things).status_code == 403
    assert _make(stranger, pid, things).status_code == 404

    guest = Guest(owner)
    opened = guest.open(link["url"])
    assert opened.status_code == 200, opened.text
    assert opened.json()["link_name"] == "Dave's Garage"
    cookie = opened.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "secure" in cookie

    seen = guest.req("GET", "/api/v1/share/view").json()
    assert [t["title"] for t in seen["tasks"]] == ["Change oil"]
    assert {n["title"] for n in seen["notes"]} == {"Instructions", "Service notes"}
    assert [li["title"] for li in seen["lists"]] == ["Parts"]
    assert [i["text"] for i in seen["lists"][0]["items"]] == ["Item in parts"]
    assert "email" not in str(seen)

    # Allowed: tick the chosen task and the chosen list's item.
    t_ok, t_private = things["tasks"]
    assert guest.req("POST", f"/api/v1/share/tasks/{t_ok}", json={"done": True}).status_code == 204
    i_ok, i_private = things["items"]
    r = guest.req("POST", f"/api/v1/share/list-items/{i_ok}", json={"checked": True})
    assert r.status_code == 204
    # Not given: another task, another list's item, a note that's only for reading.
    r = guest.req("POST", f"/api/v1/share/tasks/{t_private}", json={"done": True})
    assert r.status_code == 404
    r = guest.req("POST", f"/api/v1/share/list-items/{i_private}", json={"checked": True})
    assert r.status_code == 404
    read_only, service_notes, _ = things["notes"]
    r = guest.req("POST", f"/api/v1/share/notes/{read_only}/add", json={"text": "hi"})
    assert r.status_code == 404

    # Adding to the service notes: new text at the end, headed with who and how.
    r = guest.req(
        "POST", f"/api/v1/share/notes/{service_notes}/add", json={"text": "Oil changed\n5W-30"}
    )
    assert r.status_code == 204, r.text
    note = owner.get(f"/api/v1/notes/{service_notes}").json()
    assert "Dave (via link “Dave's Garage”)" in note["text_content"]
    assert note["text_content"].endswith("Oil changed\n\n5W-30")

    # A photo: cleaned like any upload, recorded as the link's creator's project file.
    r = guest.req(
        "POST",
        "/api/v1/share/files",
        params={"filename": "done.jpg"},
        content=jpeg_with_gps(),
        headers={"content-type": "application/octet-stream"},
    )
    assert r.status_code == 201, r.text
    photo = r.json()["id"]
    served = guest.req("GET", f"/api/v1/share/files/{photo}/view")
    assert served.status_code == 200
    assert b"Exif" not in served.content
    assert "sandbox" in served.headers["content-security-policy"]

    # The owner sees what happened, by whom.
    events = _req(owner, "GET", f"/api/v1/share-links/{link['id']}/events").json()
    assert {e["action"] for e in events} >= {"opened", "task.done", "note.added", "photo.added"}
    assert {e["guest_name"] for e in events} == {"Dave"}

    # A signed-in account doesn't get into guest routes; a guest doesn't get into the app.
    assert _req(owner, "GET", "/api/v1/share/view").status_code == 401
    assert guest.req("GET", f"/api/v1/projects/{pid}").status_code == 401
    assert guest.req("GET", f"/api/v1/notes/{read_only}").status_code == 401

    # Revoked: the session and the link stop working.
    assert _req(owner, "POST", f"/api/v1/share-links/{link['id']}/revoke").status_code == 204
    assert guest.req("GET", "/api/v1/share/view").status_code == 401
    assert guest.open(link["url"]).status_code == 404


async def _as_link(link_id: str, statement: str, params: dict[str, Any]) -> Any:
    db = Database(_settings())
    try:
        async with db.link_transaction(uuid.UUID(link_id)) as conn:
            result = await conn.execute(text(statement), params)
            return result.fetchall() if result.returns_rows else result.rowcount
    finally:
        await db.dispose()


def test_the_database_itself_refuses_what_the_link_wasnt_given(team: Team) -> None:
    owner, _, _, pid, _ = team
    things = _project(owner, pid)
    link = _make(owner, pid, things).json()
    lid = link["id"]
    t_ok, t_private = things["tasks"]

    def run(statement: str, **params: Any) -> Any:
        return asyncio.run(_as_link(lid, statement, params))

    # Reads: only the chosen task, list items of the chosen list, the chosen notes.
    assert {r[0] for r in run("SELECT id FROM tasks")} == {uuid.UUID(t_ok)}
    assert len(run("SELECT id FROM list_items")) == 1
    assert len(run("SELECT id FROM notes")) == 2
    assert run("SELECT id FROM contacts") == []
    assert run("SELECT id FROM quotes") == []
    assert run("SELECT id FROM cost_entries") == []
    assert run("SELECT user_id FROM project_members") == []
    assert run("SELECT id FROM users") == []
    assert run("SELECT id FROM share_links") == []
    # Writes: nothing outside what it was given...
    assert run("UPDATE tasks SET done_at = now() WHERE id = :t", t=t_private) == 0
    assert run("UPDATE lists SET title = 'x'") == 0
    # ...and on a task it may tick, only the tick.
    with pytest.raises(Exception, match="share link can't change this"):
        run("UPDATE tasks SET title = 'hacked' WHERE id = :t", t=t_ok)
    with pytest.raises(Exception, match="share link can't change this"):
        run("UPDATE notes SET title = 'hacked' WHERE id = :n", n=things["notes"][1])


def test_pin_expiry_and_the_creators_access(team: Team) -> None:
    owner, viewer, _, pid, _ = team
    things = _project(owner, pid)
    r = _make(owner, pid, things, pin=True)
    link = r.json()
    assert len(link["pin"]) == 6
    guest = Guest(owner)
    assert guest.open(link["url"]).status_code == 401  # PIN needed
    wrong = "000000" if link["pin"] != "000000" else "111111"
    assert guest.open(link["url"], pin=wrong).status_code == 401
    assert guest.open(link["url"], pin=link["pin"]).status_code == 200

    # Expired (a link lasts at most a year; here, made to end now).
    async def expire() -> None:
        # Nothing in the app can change an expiry; as the table owner, briefly allowed to.
        db = Database(_settings(), role=OWNER_ROLE)
        try:
            async with db.anonymous_transaction() as conn:
                await conn.execute(
                    text(
                        "CREATE POLICY test_expire ON share_links FOR UPDATE TO planhaven_owner "
                        "USING (true)"
                    )
                )
                await conn.execute(
                    text("UPDATE share_links SET expires_at = now() WHERE id = :l"),
                    {"l": link["id"]},
                )
                await conn.execute(text("DROP POLICY test_expire ON share_links"))
        finally:
            await db.dispose()

    asyncio.run(expire())
    assert guest.req("GET", "/api/v1/share/view").status_code == 401
    assert guest.open(link["url"], pin=link["pin"]).status_code == 404
    assert _make(owner, pid, things, days=400).status_code == 422

    # A link made by an editor stops when they're no longer an editor.
    _req(owner, "PATCH", f"/api/v1/projects/{pid}/members/{viewer.id}", json={"role": "editor"})
    by_editor = _make(viewer, pid, things).json()
    guest2 = Guest(owner)
    assert guest2.open(by_editor["url"], name="Sam").status_code == 200
    _req(owner, "PATCH", f"/api/v1/projects/{pid}/members/{viewer.id}", json={"role": "viewer"})
    assert guest2.req("GET", "/api/v1/share/view").status_code == 401

    # Made-up and malformed tokens look the same as dead ones.
    for token in ("phv_shr_" + "A" * 43, "nope", "phv_shr_' OR 1=1 --"):
        r = owner.client.post("/api/v1/share/open", json={"token": token, "name": "X"})
        assert r.status_code == 404


def test_a_full_note_says_so(team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, _, _, pid, _ = team
    things = _project(owner, pid)
    link = _make(owner, pid, things).json()
    guest = Guest(owner)
    guest.open(link["url"])
    monkeypatch.setattr(note_content, "MAX_TEXT", 50)
    r = guest.req("POST", f"/api/v1/share/notes/{things['notes'][1]}/add", json={"text": "x" * 100})
    assert r.status_code == 422
    assert "full" in r.json()["detail"]

"""Messages between people and online status (ADR 0018): only a conversation's current
members see it (admins included: no access), notifications once until read, deleting removes
the text everywhere."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.database import Database
from tests.db import team as setup
from tests.db.conftest import _settings
from tests.db.team import U

pytestmark = pytest.mark.db

team = setup.team  # owner (an admin), viewer, stranger, project, note

type Team = tuple[U, U, U, str, str]


def _req(u: U, method: str, path: str, **kw: Any) -> Any:
    u._cookie()
    return u.client.request(method, path, headers={**u.h, **kw.pop("headers", {})}, **kw)


def _start(u: U, people: list[str], title: str | None = None) -> Any:
    body: dict[str, Any] = {"people": people}
    if title:
        body["title"] = title
    return _req(u, "POST", "/api/v1/conversations", json=body)


def _send(u: U, cid: str, words: str) -> Any:
    return _req(u, "POST", f"/api/v1/conversations/{cid}/messages", json={"body": words})


def _message_notices(u: U) -> list[dict[str, Any]]:
    return [n for n in _req(u, "GET", "/api/v1/notifications").json() if n["kind"] == "message"]


def test_one_to_one(team: Team) -> None:
    ann, bob, cat, _, _ = team
    r = _start(ann, [bob.id])
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert (r.json()["title"], r.json()["is_group"]) == ("viewer", False)
    assert _start(ann, [bob.id]).json()["id"] == cid  # one per pair
    assert _start(bob, [ann.id]).json()["id"] == cid

    assert _send(ann, cid, "  Can you grab oil?  ").json()["body"] == "Can you grab oil?"
    _send(ann, cid, "5W-30")
    listed = _req(bob, "GET", "/api/v1/conversations").json()
    assert [(c["id"], c["unread"], c["last_preview"]) for c in listed] == [(cid, 2, "5W-30")]
    texts = [m["body"] for m in _req(bob, "GET", f"/api/v1/conversations/{cid}/messages").json()]
    assert texts == ["5W-30", "Can you grab oil?"]  # newest first

    # One notification until Bob reads the conversation, with a preview.
    notices = _message_notices(bob)
    assert [(n["title"], n["body"], n["url"]) for n in notices] == [
        ("Message from Ann", "Can you grab oil?", f"/messages/{cid}")
    ]
    assert _req(bob, "POST", f"/api/v1/conversations/{cid}/read").status_code == 204
    assert all(n["read"] for n in _message_notices(bob))
    _send(ann, cid, "Thanks!")
    assert len(_message_notices(bob)) == 2

    # Previews can be turned off.
    _req(bob, "PUT", "/api/v1/notification-settings", json={"prefs": {}, "previews": False})
    assert _message_notices(bob)[0]["body"] == "New message"

    # Outsiders, the admin included, see nothing; one-to-one stays one-to-one.
    for path in (f"/api/v1/conversations/{cid}", f"/api/v1/conversations/{cid}/messages"):
        assert _req(cat, "GET", path).status_code == 404
    assert _send(cat, cid, "hi").status_code == 404
    add = {"user_id": cat.id}
    assert _req(ann, "POST", f"/api/v1/conversations/{cid}/members", json=add).status_code == 422
    assert _req(ann, "POST", f"/api/v1/conversations/{cid}/leave").status_code == 422


def test_admin_cannot_read_others(team: Team) -> None:
    admin, bob, cat, _, _ = team
    cid = _start(bob, [cat.id]).json()["id"]
    _send(bob, cid, "Private")
    assert _req(admin, "GET", f"/api/v1/conversations/{cid}/messages").status_code == 404
    assert cid not in [c["id"] for c in _req(admin, "GET", "/api/v1/conversations").json()]


def test_deleting_removes_the_text(team: Team) -> None:
    ann, bob, _, _, _ = team
    cid = _start(ann, [bob.id]).json()["id"]
    _req(bob, "POST", f"/api/v1/conversations/{cid}/read")
    mid = _send(ann, cid, "Gate code is 1234").json()["id"]
    assert _req(bob, "DELETE", f"/api/v1/messages/{mid}").status_code == 403
    assert _req(ann, "DELETE", f"/api/v1/messages/{mid}").status_code == 204
    shown = _req(bob, "GET", f"/api/v1/conversations/{cid}/messages").json()[0]
    assert (shown["body"], shown["deleted"]) == ("", True)
    notice = next(
        n for n in _message_notices(bob) if "1234" in str(n) or n["body"] == "New message"
    )
    assert "1234" not in str(notice)
    assert _req(bob, "GET", "/api/v1/conversations").json()[0]["last_preview"] == "Message deleted"


def test_groups(team: Team) -> None:
    ann, bob, cat, _, _ = team
    assert _start(ann, [bob.id, cat.id]).status_code == 422  # a group needs a name
    cid = _start(ann, [bob.id], "Boat crew").json()["id"]
    assert _req(cat, "GET", f"/api/v1/conversations/{cid}").status_code == 404
    rename = {"title": "Dock crew"}
    assert _req(bob, "PATCH", f"/api/v1/conversations/{cid}", json=rename).status_code == 204
    add = {"user_id": cat.id}
    assert _req(bob, "POST", f"/api/v1/conversations/{cid}/members", json=add).status_code == 204
    group = _req(cat, "GET", f"/api/v1/conversations/{cid}").json()
    assert (group["title"], len(group["members"])) == ("Dock crew", 3)
    _send(cat, cid, "Hi all")
    assert _message_notices(ann)[0]["title"] == "stranger in Dock crew"

    # Leaving: no more access, and the others see two members.
    assert _req(cat, "POST", f"/api/v1/conversations/{cid}/leave").status_code == 204
    assert _req(cat, "GET", f"/api/v1/conversations/{cid}/messages").status_code == 404
    assert len(_req(ann, "GET", f"/api/v1/conversations/{cid}").json()["members"]) == 2
    # Unknown people can't be added or messaged.
    nobody = {"user_id": "00000000-0000-7000-8000-000000000000"}
    assert _req(ann, "POST", f"/api/v1/conversations/{cid}/members", json=nobody).status_code == 404
    assert _start(ann, ["00000000-0000-7000-8000-000000000000"]).status_code == 404


async def _as(user_id: str, sql: str, params: dict[str, Any]) -> None:
    db = Database(_settings())
    try:
        async with db.user_transaction(uuid.UUID(user_id)) as conn:
            await conn.execute(text(sql), params)
    finally:
        await db.dispose()


def test_database_refuses_direct_writes(team: Team) -> None:
    """The same rules hold in the database, without the service in front."""
    import asyncio

    ann, bob, cat, _, _ = team
    cid = _start(ann, [bob.id]).json()["id"]
    cases = [
        # Adding a third person to a one-to-one conversation.
        (
            ann.id,
            "INSERT INTO conversation_members (conversation_id, user_id) VALUES (:c, :u)",
            {"c": cid, "u": cat.id},
        ),
        # Writing into a conversation you're not in.
        (
            cat.id,
            "INSERT INTO messages (conversation_id, sender_id, body) VALUES (:c, :u, 'x')",
            {"c": cid, "u": cat.id},
        ),
        # Marking someone else as having left.
        (
            ann.id,
            "UPDATE conversation_members SET left_at = now() "
            "WHERE conversation_id = :c AND user_id = :u",
            {"c": cid, "u": bob.id},
        ),
    ]
    for user_id, sql, params in cases:
        with pytest.raises(DBAPIError):
            asyncio.run(_as(user_id, sql, params))


def test_people_and_online_status(team: Team) -> None:
    ann, bob, _, _, _ = team
    people = {p["name"]: p for p in _req(ann, "GET", "/api/v1/people/status").json()}
    assert set(people) == {"viewer", "stranger"}  # everyone else
    assert people["viewer"]["online"] is False
    with bob.ws("/api/v1/live/me"):
        status = {p["name"]: p for p in _req(ann, "GET", "/api/v1/people/status").json()}
        assert status["viewer"]["online"] is True
        assert status["viewer"]["last_seen"] is not None
        # Hidden: neither online nor last seen.
        assert _req(bob, "PUT", "/api/v1/presence", json={"hidden": True}).status_code == 200
        status = {p["name"]: p for p in _req(ann, "GET", "/api/v1/people/status").json()}
        assert (status["viewer"]["online"], status["viewer"]["last_seen"]) == (False, None)
    assert _req(bob, "GET", "/api/v1/presence").json() == {"hidden": True}


def test_new_messages_reach_open_apps(team: Team) -> None:
    ann, bob, _, _, _ = team
    cid = _start(ann, [bob.id]).json()["id"]
    with bob.ws("/api/v1/live/me") as ws:
        _send(ann, cid, "Here?")
        assert ws.receive_json() == {"kind": "messages"}
        assert ws.receive_json() == {"kind": "notifications"}


def test_sending_is_rate_limited(team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import limits

    ann, bob, _, _, _ = team
    cid = _start(ann, [bob.id]).json()["id"]
    monkeypatch.setattr(
        limits, "MESSAGE_SEND", limits.Limit("test-message-send", capacity=2, per_second=0.001)
    )
    assert [_send(ann, cid, f"hi {i}").status_code for i in range(3)] == [201, 201, 429]

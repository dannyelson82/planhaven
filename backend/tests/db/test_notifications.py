"""Notifications screen, settings, phone alert devices, sending and reminders (ADR 0018)."""

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import text

from app.db import notifications as store
from app.db.database import Database
from app.push import webpush
from app.services import notifications as service
from tests.db.test_projects import User, _project, _share

pytestmark = [pytest.mark.db, pytest.mark.anyio]


def _keys() -> dict[str, str]:
    public = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    return {"p256dh": _b64(public), "auth": _b64(b"0123456789abcdef")}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _device(endpoint: str = "") -> dict[str, str]:
    return {
        "endpoint": endpoint or f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4().hex}",
        **_keys(),
        "label": "Phone",
    }


async def _notify(db: Database, user: User, kind: str = "task_due", **data: Any) -> None:
    async with db.system_transaction() as conn:
        await store.notify(conn, user.id, kind, {"title": "Oil", **data})


class FakeSender:
    """Stands in for webpush.Sender: records what would be sent, answers with `status`."""

    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.sent: list[tuple[str, bytes]] = []

    def send(self, target: webpush.Target, body: bytes) -> int:
        self.sent.append((target.endpoint, body))
        return self.status


async def test_list_unread_and_settings(people: dict[str, User], db: Database) -> None:
    ann, bob = people["owner"], people["viewer"]
    # Signing up left security notices; start from none unread.
    for u in (ann, bob):
        await u.client.post("/api/v1/notifications/read-all", headers=u.h)
    await _notify(db, ann, project_id="p1", project_title="Boat")
    await _notify(db, ann, "shared_with_you", by="Bob", project_id="p2")
    await _notify(db, bob)

    listed = (await ann.client.get("/api/v1/notifications")).json()[:2]
    assert [n["title"] for n in listed] == ["Bob shared “Oil” with you", "Due today: Oil"]
    assert listed[1]["url"] == "/projects/p1"
    assert (await ann.client.get("/api/v1/notifications/unread")).json() == {"count": 2}

    # Turning a group off hides it from the list and the count.
    put = await ann.client.put(
        "/api/v1/notification-settings",
        headers=ann.h,
        json={
            "prefs": {"tasks": "off", "shared": "app"},
            "quiet_from": "22:00",
            "quiet_to": "07:00",
            "time_zone": "America/Toronto",
        },
    )
    assert put.status_code == 200, put.text
    assert put.json()["prefs"] == {
        "shared": "app",
        "tasks": "off",
        "service": "push",
        "share_links": "push",
        "security": "push",
    }
    assert (await ann.client.get("/api/v1/notifications/unread")).json() == {"count": 1}
    for bad in (
        {"prefs": {"security": "off"}},
        {"prefs": {"tasks": "loud"}},
        {"prefs": {}, "quiet_from": "22:00"},
        {"prefs": {}, "time_zone": "Mars/Olympus"},
    ):
        r = await ann.client.put("/api/v1/notification-settings", headers=ann.h, json=bad)
        assert r.status_code == 422, bad

    assert (
        await ann.client.post("/api/v1/notifications/read-all", headers=ann.h)
    ).status_code == 204
    assert (await ann.client.get("/api/v1/notifications/unread")).json() == {"count": 0}
    # Bob's are his own.
    assert (await bob.client.get("/api/v1/notifications/unread")).json() == {"count": 1}


async def test_devices(people: dict[str, User], db: Database) -> None:
    ann, bob = people["owner"], people["viewer"]
    url = "/api/v1/push/devices"
    for endpoint in ("https://evil.example.com/x", "http://fcm.googleapis.com/x"):
        r = await ann.client.post(url, headers=ann.h, json=_device(endpoint))
        assert r.status_code == 422
    bad_keys = {**_device(), "auth": base64.urlsafe_b64encode(b"short").decode()}
    assert (await ann.client.post(url, headers=ann.h, json=bad_keys)).status_code == 422

    shared = _device()
    made = await ann.client.post(url, headers=ann.h, json=shared)
    assert made.status_code == 201, made.text
    assert [d["label"] for d in (await ann.client.get(url)).json()] == ["Phone"]
    assert (await bob.client.get(url)).json() == []
    assert (await bob.client.delete(f"{url}/{made.json()['id']}", headers=bob.h)).status_code == 404

    # Bob signs in on the same browser and turns alerts on: it's his now, not Ann's.
    assert (await bob.client.post(url, headers=bob.h, json=shared)).status_code == 201
    assert (await ann.client.get(url)).json() == []
    # Signing out forgets this browser for him.
    forget = {"endpoint": shared["endpoint"]}
    assert (
        await bob.client.post("/api/v1/push/forget", headers=bob.h, json=forget)
    ).status_code == 204
    assert (await bob.client.get(url)).json() == []


async def test_sending(people: dict[str, User], db: Database) -> None:
    ann, bob = people["owner"], people["viewer"]
    async with db.system_transaction() as conn:
        await conn.execute(text("UPDATE notifications SET push_state = 'none'"))
    phone = _device()
    await ann.client.post("/api/v1/push/devices", headers=ann.h, json=phone)
    await _notify(db, ann, project_id="p1")
    await _notify(db, bob)  # Bob has no device: skipped
    sender = FakeSender()
    assert await service.dispatch(db, sender) == 2
    assert [e for e, _ in sender.sent] == [phone["endpoint"]]
    assert b"Due today: Oil" in sender.sent[0][1]  # the payload before encryption
    assert await service.dispatch(db, sender) == 0  # nothing left

    # Quiet hours hold an alert until they end; "in the app only" never sends.
    await ann.client.put(
        "/api/v1/notification-settings",
        headers=ann.h,
        json={"prefs": {"shared": "app"}, "quiet_from": "00:00", "quiet_to": "23:59"},
    )
    await _notify(db, ann)
    await _notify(db, ann, "shared_with_you")
    await service.dispatch(db, sender)
    assert len(sender.sent) == 1
    async with db.system_transaction() as conn:
        states = (
            await conn.execute(
                text(
                    "SELECT kind, push_state, push_after > now() + interval '6 minutes' AS later "
                    "FROM notifications WHERE user_id = :u "
                    "AND push_state IN ('pending', 'skipped') AND kind <> 'security_change'"
                ),
                {"u": ann.id},
            )
        ).all()
    assert sorted((s.kind, s.push_state, s.later) for s in states) == [
        ("shared_with_you", "skipped", False),
        ("task_due", "pending", True),
    ]

    # A browser that unsubscribed (410) is forgotten.
    await ann.client.put("/api/v1/notification-settings", headers=ann.h, json={"prefs": {}})
    await ann.client.post("/api/v1/push/test", headers=ann.h)
    await service.dispatch(db, FakeSender(410))
    assert (await ann.client.get("/api/v1/push/devices")).json() == []


async def test_reminders(people: dict[str, User], db: Database) -> None:
    ann, viewer = people["owner"], people["viewer"]
    pid = (await _project(ann, title="Boat"))["id"]
    await _share(db, ann, str(pid), viewer, "viewer")
    today = datetime.now(UTC).date()
    for title, day in (
        ("Today", today),
        ("Late", today - timedelta(days=2)),
        ("Old", today - timedelta(days=30)),
    ):
        await ann.client.post(
            f"/api/v1/projects/{pid}/tasks",
            headers=ann.h,
            json={"title": title, "due_at": f"{day}T00:00:00Z", "due_all_day": True},
        )
    # A service due soon on an asset.
    boat = (
        await ann.client.post(
            "/api/v1/assets", headers=ann.h, json={"name": "Outboard", "kind": "boat"}
        )
    ).json()
    oil = (
        await ann.client.post(
            f"/api/v1/assets/{boat['id']}/service-schedules",
            headers=ann.h,
            json={"name": "Engine oil", "every_months": 1},
        )
    ).json()
    done = (today - timedelta(days=25)).isoformat()
    await ann.client.post(
        f"/api/v1/assets/{boat['id']}/service-records",
        headers=ann.h,
        json={"schedule_id": oil["id"], "done_on": done},
    )

    added = await service.remind(db)
    assert await service.remind(db) == 0  # once only
    assert added == 3
    titles = {n["title"] for n in (await ann.client.get("/api/v1/notifications")).json()}
    assert {"Due today: Today", "Overdue: Late", "Due soon: Engine oil"} <= titles
    assert not any("Old" in t for t in titles)
    # The viewer isn't told about tasks (not assigned, can't change them).
    viewer_titles = [n["title"] for n in (await viewer.client.get("/api/v1/notifications")).json()]
    assert not any(t.startswith(("Due today", "Overdue")) for t in viewer_titles)

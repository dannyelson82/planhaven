"""Contacts shared one by one; quotes and costs on projects (phase 0.2, M5)."""

import asyncio
import base64
from typing import Any

import pytest

from app.db import attachments as attachment_store
from app.db.database import Database
from app.services import vcard
from tests.db import team as setup
from tests.db.conftest import _settings
from tests.db.team import U
from tests.test_files import jpeg_with_gps

pytestmark = pytest.mark.db

team = setup.team  # the shared fixture: owner, viewer, stranger, project, note

type Team = tuple[U, U, U, str, str]
PLUMBER = {"name": "Dave Pipes", "company": "Pipes & Co", "phone": "555-0100"}


def _req(u: U, method: str, path: str, **kw: Any) -> Any:
    u._cookie()
    return u.client.request(method, path, headers={**u.h, **kw.pop("headers", {})}, **kw)


def test_contacts_are_private_until_shared(team: Team) -> None:
    owner, viewer, stranger, _, _ = team
    r = owner.post("/api/v1/contacts", headers=owner.h, json=PLUMBER)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert viewer.get(f"/api/v1/contacts/{cid}").status_code == 404
    assert viewer.get("/api/v1/contacts").json() == []
    r = owner.post(
        f"/api/v1/contacts/{cid}/members",
        headers=owner.h,
        json={"user_id": viewer.id, "role": "viewer"},
    )
    assert r.status_code == 201, r.text
    assert viewer.get(f"/api/v1/contacts/{cid}").json()["phone"] == "555-0100"
    r = _req(viewer, "PUT", f"/api/v1/contacts/{cid}", json=PLUMBER, headers={"if-match": '"1"'})
    assert r.status_code == 403
    assert _req(stranger, "DELETE", f"/api/v1/contacts/{cid}").status_code == 404
    bad = {**PLUMBER, "website": "javascript:alert(1)"}
    r = _req(owner, "PUT", f"/api/v1/contacts/{cid}", json=bad, headers={"if-match": '"1"'})
    assert r.status_code == 422
    r = _req(owner, "PATCH", f"/api/v1/contacts/{cid}/members/{owner.id}", json={"role": "viewer"})
    assert r.status_code == 409


def test_quotes_and_costs(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    cid = owner.post("/api/v1/contacts", headers=owner.h, json=PLUMBER).json()["id"]
    theirs = stranger.post("/api/v1/contacts", headers=stranger.h, json={"name": "X"}).json()["id"]

    # A quote can't name a contact you can't see; viewers can't add quotes.
    r = owner.post(
        f"/api/v1/projects/{pid}/quotes", headers=owner.h, json={"title": "Q", "contact_id": theirs}
    )
    assert r.status_code == 404
    assert (
        viewer.post(
            f"/api/v1/projects/{pid}/quotes", headers=viewer.h, json={"title": "Q"}
        ).status_code
        == 403
    )
    r = owner.post(
        f"/api/v1/projects/{pid}/quotes",
        headers=owner.h,
        json={"title": "Replace water heater", "contact_id": cid, "amount_cents": 185000},
    )
    assert r.status_code == 201, r.text
    quote = r.json()
    assert quote["contact_name"] == "Dave Pipes"

    # A project viewer who can't see the contact sees the quote without the contact's name.
    seen = viewer.get(f"/api/v1/projects/{pid}/quotes").json()
    assert [q["title"] for q in seen] == ["Replace water heater"]
    assert seen[0]["contact_name"] is None
    assert stranger.get(f"/api/v1/projects/{pid}/quotes").status_code == 404

    r = _req(
        owner,
        "PATCH",
        f"/api/v1/quotes/{quote['id']}",
        json={"status": "accepted"},
        headers={"if-match": f'"{quote["version"]}"'},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"
    assert r.json()["amount_cents"] == 185000  # untouched fields keep their value

    # Costs, one linked to the accepted quote; a quote from another project is refused.
    r = owner.post(
        f"/api/v1/projects/{pid}/costs",
        headers=owner.h,
        json={"description": "Water heater", "amount_cents": 185000, "quote_id": quote["id"]},
    )
    assert r.status_code == 201, r.text
    other = owner.post("/api/v1/projects", headers=owner.h, json={"title": "Other"}).json()["id"]
    r = owner.post(
        f"/api/v1/projects/{other}/costs",
        headers=owner.h,
        json={"description": "x", "amount_cents": 1, "quote_id": quote["id"]},
    )
    assert r.status_code == 422
    costs = viewer.get(f"/api/v1/projects/{pid}/costs").json()
    assert [c["amount_cents"] for c in costs] == [185000]

    # The contact's page lists its quotes.
    assert [q["id"] for q in owner.get(f"/api/v1/contacts/{cid}").json()["quotes"]] == [quote["id"]]

    # Deleting goes to the trash and can be undone.
    assert _req(owner, "DELETE", f"/api/v1/quotes/{quote['id']}").status_code == 204
    kinds = {i["kind"] for i in owner.get("/api/v1/trash").json()}
    assert "quote" in kinds
    assert _req(owner, "POST", f"/api/v1/trash/quote/{quote['id']}/restore").status_code == 204
    assert _req(owner, "DELETE", f"/api/v1/contacts/{cid}").status_code == 204
    assert _req(owner, "POST", f"/api/v1/trash/contact/{cid}/restore").status_code == 204


def test_contact_photo(team: Team) -> None:
    owner, viewer, stranger, _, _ = team
    cid = owner.post("/api/v1/contacts", headers=owner.h, json=PLUMBER).json()["id"]
    assert owner.get(f"/api/v1/contacts/{cid}").json()["has_photo"] is False
    r = _req(
        owner,
        "PUT",
        f"/api/v1/contacts/{cid}/photo",
        content=jpeg_with_gps(),
        headers={"content-type": "application/octet-stream"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_photo"] is True
    _req(
        owner,
        "POST",
        f"/api/v1/contacts/{cid}/members",
        json={"user_id": viewer.id, "role": "viewer"},
    )
    photo = viewer.get(f"/api/v1/contacts/{cid}/photo")
    assert photo.status_code == 200
    assert b"Exif" not in photo.content  # location removed
    assert "sandbox" in photo.headers["content-security-policy"]
    thumb = viewer.get(f"/api/v1/contacts/{cid}/photo/thumbnail")
    assert thumb.headers["content-type"] == "image/webp"
    assert stranger.get(f"/api/v1/contacts/{cid}/photo").status_code == 404
    assert (
        _req(viewer, "PUT", f"/api/v1/contacts/{cid}/photo", content=jpeg_with_gps()).status_code
        == 403
    )
    assert _req(viewer, "DELETE", f"/api/v1/contacts/{cid}/photo").status_code == 403
    pdf = _req(owner, "PUT", f"/api/v1/contacts/{cid}/photo", content=b"%PDF-1.7\n")
    assert pdf.status_code == 415

    # The blob purge keeps files a contact uses.
    async def referenced() -> set[str]:
        db = Database(_settings())
        try:
            async with db.system_transaction() as conn:
                return await attachment_store.referenced_blobs(conn)
        finally:
            await db.dispose()

    assert len(asyncio.run(referenced())) >= 2  # the photo and its thumbnail
    assert _req(owner, "DELETE", f"/api/v1/contacts/{cid}/photo").status_code == 204
    assert owner.get(f"/api/v1/contacts/{cid}/photo").status_code == 404
    assert owner.get(f"/api/v1/contacts/{cid}").json()["has_photo"] is False


def test_contact_cards_from_and_to_a_phone(team: Team) -> None:
    owner, viewer, stranger, _, _ = team
    photo = base64.b64encode(jpeg_with_gps()).decode()
    card = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Pipes;Dave;;;\r\nFN:Dave Pipes\r\nORG:Pipes & Co;\r\n"
        "TEL;type=CELL:555-0100\r\nEMAIL:dave@example.com\r\nURL:www.davepipes.example\r\n"
        f"PHOTO;ENCODING=b;TYPE=JPEG:{photo}\r\nEND:VCARD\r\n"
    )
    r = _req(
        owner,
        "POST",
        "/api/v1/contacts/import",
        params={"kind": "supplier"},
        content=card.encode(),
        headers={"content-type": "application/octet-stream"},
    )
    assert r.status_code == 201, r.text
    made = r.json()
    assert (made["name"], made["company"], made["kind"]) == ("Dave Pipes", "Pipes & Co", "supplier")
    assert (made["phone"], made["website"]) == ("555-0100", "https://www.davepipes.example")
    assert made["has_photo"] is True
    assert b"Exif" not in owner.get(f"/api/v1/contacts/{made['id']}/photo").content

    # Saved to a phone: the same details and the cleaned photo.
    out = owner.get(f"/api/v1/contacts/{made['id']}/vcard")
    assert out.status_code == 200
    assert out.headers["content-type"].startswith("text/vcard")
    assert "attachment" in out.headers["content-disposition"]
    back = vcard.parse(out.content)
    assert (back.name, back.company, back.email) == ("Dave Pipes", "Pipes & Co", "dave@example.com")
    assert back.photo is not None
    assert b"Exif" not in back.photo
    assert viewer.get(f"/api/v1/contacts/{made['id']}/vcard").status_code == 404
    assert stranger.get(f"/api/v1/contacts/{made['id']}/vcard").status_code == 404

    bad = _req(owner, "POST", "/api/v1/contacts/import", content=b"not a card")
    assert bad.status_code == 422
    assert "contact card" in bad.json()["detail"]

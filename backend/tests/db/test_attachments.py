"""Attachments end to end: upload pipeline, roles, and safe download headers (S§7.5)."""

import io
import os
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.files import images
from app.services import attachments as attachment_service
from app.services import limits
from tests.db import team as setup
from tests.db.team import U
from tests.test_files import jpeg_with_gps

pytestmark = pytest.mark.db

team = setup.team  # the shared fixture: owner, viewer, stranger, project, note

type Team = tuple[U, U, U, str, str]


def _upload(u: U, pid: str, data: bytes, name: str, **params: object) -> Any:
    return u.post(
        f"/api/v1/projects/{pid}/attachments",
        headers={**u.h, "content-type": "application/octet-stream"},
        params={"filename": name, **params},
        content=data,
    )


def test_photo_upload_strips_location_and_serves_safely(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    r = _upload(owner, pid, jpeg_with_gps(), "deck.png")
    assert r.status_code == 201, r.text
    a = r.json()
    assert (a["filename"], a["kind"], a["content_type"]) == ("deck.jpg", "image", "image/jpeg")
    assert a["has_thumbnail"]
    assert not a["metadata_kept"]

    listed = viewer.get(f"/api/v1/projects/{pid}/attachments").json()
    assert [x["id"] for x in listed] == [a["id"]]

    d = viewer.get(f"/api/v1/attachments/{a['id']}/download")
    assert d.status_code == 200
    assert d.headers["content-disposition"].startswith('attachment; filename="deck.jpg"')
    assert d.headers["content-type"] == "application/octet-stream"
    assert d.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in d.headers["content-security-policy"]
    assert b"Exif" not in d.content
    with Image.open(io.BytesIO(d.content)) as im:
        assert not im.getexif()

    v = viewer.get(f"/api/v1/attachments/{a['id']}/view")
    assert v.headers["content-type"] == "image/jpeg"
    assert v.headers["content-disposition"].startswith("inline")
    t = viewer.get(f"/api/v1/attachments/{a['id']}/thumbnail")
    assert t.headers["content-type"] == "image/webp"

    for path in ("", "/download", "/view", "/thumbnail"):
        assert stranger.get(f"/api/v1/attachments/{a['id']}{path}").status_code == 404


def test_roles(team: Team) -> None:
    owner, viewer, stranger, pid, _ = team
    assert _upload(viewer, pid, b"notes\n", "a.txt").status_code == 403
    assert _upload(stranger, pid, b"notes\n", "a.txt").status_code == 404
    aid = _upload(owner, pid, b"notes\n", "a.txt").json()["id"]
    assert viewer.get(f"/api/v1/attachments/{aid}").json()["can_delete"] is False
    viewer._cookie()
    assert owner.client.delete(f"/api/v1/attachments/{aid}", headers=viewer.h).status_code == 403
    owner._cookie()
    assert owner.client.delete(f"/api/v1/attachments/{aid}", headers=owner.h).status_code == 204
    assert owner.get(f"/api/v1/attachments/{aid}").status_code == 404


def test_refusals(team: Team) -> None:
    owner, _, _, pid, _ = team
    r = _upload(owner, pid, b"MZ\x90\x00\x03" + b"\x00" * 50, "setup.exe")
    assert r.status_code == 415
    r = _upload(owner, pid, b"\xff\xd8\xff\xe0" + b"\x00" * 100, "broken.jpg")
    assert r.status_code == 415
    assert _upload(owner, pid, b"", "empty.txt").status_code == 415
    # Other routes keep the small JSON body limit.
    r = owner.post(f"/api/v1/projects/{pid}/notes", headers=owner.h, content=b"x" * 5000)
    assert r.status_code == 413


def test_html_is_never_served_as_html(team: Team) -> None:
    owner, _, _, pid, _ = team
    a = _upload(owner, pid, b"<html><script>alert(1)</script>", "x.html").json()
    assert (a["filename"], a["content_type"]) == ("x.txt", "text/plain")
    assert owner.get(f"/api/v1/attachments/{a['id']}/view").status_code == 404
    d = owner.get(f"/api/v1/attachments/{a['id']}/download")
    assert d.headers["content-type"] == "application/octet-stream"


def test_uploads_are_rate_limited(team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, _, _, pid, _ = team
    tight = limits.Limit("upload-user-test", capacity=1, per_second=1 / 3600)
    monkeypatch.setattr(attachment_service, "UPLOAD_USER", tight)
    assert _upload(owner, pid, b"one\n", "a.txt").status_code == 201
    r = _upload(owner, pid, b"two\n", "b.txt")
    assert r.status_code == 429
    assert "retry-after" in r.headers


@pytest.mark.skipif(
    images.heic_tool() is None and not os.environ.get("PLANHAVEN_REQUIRE_HEIC"),
    reason="HEIC decoder (libheif) not installed",
)
def test_iphone_photos_become_jpeg_without_location(team: Team) -> None:
    owner, _, _, pid, _ = team
    heic = (Path(__file__).parent.parent / "fixtures" / "iphone-photo.heic").read_bytes()
    r = _upload(owner, pid, heic, "IMG_0001.HEIC")
    assert r.status_code == 201, r.text
    a = r.json()
    assert (a["filename"], a["content_type"], a["has_thumbnail"]) == (
        "IMG_0001.jpg",
        "image/jpeg",
        True,
    )
    data = owner.get(f"/api/v1/attachments/{a['id']}/download").content
    with Image.open(io.BytesIO(data)) as im:
        assert im.format == "JPEG"
        assert im.size == (64, 48)
        assert not im.getexif().get_ifd(0x8825)  # no GPS
    assert b"Exif" not in data

    # Keeping the location keeps the original file; the thumbnail still works.
    kept = _upload(owner, pid, heic, "IMG_0002.HEIC", keep_metadata="true").json()
    assert (kept["filename"], kept["metadata_kept"], kept["has_thumbnail"]) == (
        "IMG_0002.heic",
        True,
        True,
    )
    assert owner.get(f"/api/v1/attachments/{kept['id']}/download").content == heic


def test_files_for_a_list_item(team: Team) -> None:
    """A file can belong to one list item of its own project (owner request, 2026-10-02)."""
    owner, viewer, stranger, pid, _ = team
    lid = owner.post(f"/api/v1/projects/{pid}/lists", headers=owner.h, json={"title": "Parts"})
    item = owner.post(
        f"/api/v1/lists/{lid.json()['id']}/items", headers=owner.h, json={"text": "Impeller"}
    ).json()
    r = _upload(owner, pid, b"%PDF-1.4\n%%EOF\n", "manual.pdf", list_item_id=item["id"])
    assert r.status_code == 201, r.text
    assert r.json()["list_item_id"] == item["id"]
    listed = viewer.get(f"/api/v1/projects/{pid}/attachments").json()
    assert [a["list_item_id"] for a in listed if a["id"] == r.json()["id"]] == [item["id"]]

    # Another project's item (even the uploader's own), or one they can't see: not found.
    other = owner.post("/api/v1/projects", headers=owner.h, json={"title": "Other"}).json()["id"]
    assert _upload(owner, other, b"%PDF-1.4\n", "x.pdf", list_item_id=item["id"]).status_code == 404
    spid = stranger.post("/api/v1/projects", headers=stranger.h, json={"title": "S"}).json()["id"]
    slid = stranger.post(
        f"/api/v1/projects/{spid}/lists", headers=stranger.h, json={"title": "L"}
    ).json()["id"]
    sitem = stranger.post(
        f"/api/v1/lists/{slid}/items", headers=stranger.h, json={"text": "Theirs"}
    ).json()
    assert _upload(owner, pid, b"%PDF-1.4\n", "y.pdf", list_item_id=sitem["id"]).status_code == 404

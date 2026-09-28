"""Attachments end to end: upload pipeline, roles, and safe download headers (S§7.5)."""

import io
from typing import Any

import pytest
from PIL import Image

from app.services import attachments as attachment_service
from app.services import limits
from tests.db import test_collab
from tests.db.test_collab import U
from tests.test_files import jpeg_with_gps

pytestmark = pytest.mark.db

team = test_collab.team  # the shared fixture: owner, viewer, stranger, project, note

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

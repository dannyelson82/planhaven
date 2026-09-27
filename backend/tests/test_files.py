"""File handling without a database: type detection, the blob store and image clean-up."""

import asyncio
import io
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from PIL import Image

from app.files import images, sniff
from app.files.blobs import BlobStore, TooLargeError


def jpeg_with_gps() -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90°
    exif[0x8825] = {1: "N", 2: (51.0, 30.0, 0.0), 3: "W", 4: (0.0, 7.0, 0.0)}
    out = io.BytesIO()
    Image.new("RGB", (64, 32), "red").save(out, "JPEG", exif=exif)
    return out.getvalue()


@pytest.mark.parametrize(
    ("head", "name", "kind", "mime"),
    [
        (b"\xff\xd8\xff\xe0rest", "photo.png", "image", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n...", "x", "image", "image/png"),
        (b"%PDF-1.7\n", "manual.pdf", "pdf", "application/pdf"),
        (b"PK\x03\x04....", "quote.docx", "document", sniff._ZIP_DOCUMENTS["docx"]),
        (b"PK\x03\x04....", "evil.html", "archive", "application/zip"),
        (b"part,qty\nbolt,4\n", "parts.csv", "text", "text/csv"),
        (b"<html><script>alert(1)</script>", "page.html", "text", "text/plain"),
        (b"<svg onload=alert(1)>", "logo.svg", "text", "text/plain"),
    ],
)
def test_type_comes_from_the_bytes(head: bytes, name: str, kind: str, mime: str) -> None:
    detected = sniff.detect(head, name, 1000)
    assert detected is not None
    assert (detected.kind, detected.mime) == (kind, mime)


def test_unknown_binary_is_refused() -> None:
    assert sniff.detect(b"\x7fELF\x02\x01\x01\x00\x00", "tool.exe", 9) is None
    assert sniff.detect(b"MZ\x90\x00\x03\x00\x00\x00", "setup.exe", 9) is None


def test_filenames_are_display_data_only() -> None:
    assert sniff.safe_filename("../../etc/passwd", sniff.TEXT) == "passwd.txt"
    assert sniff.safe_filename('C:\\a\\b"<x>.jpg', sniff.JPEG) == "bx.jpg"
    assert sniff.safe_filename("page.html", sniff.TEXT) == "page.txt"
    assert sniff.safe_filename("...", sniff.PDF) == "file.pdf"
    assert sniff.safe_filename("a\u202egnp.exe", sniff.PNG) == "agnp.png"


def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    async def gen() -> AsyncIterator[bytes]:
        for p in parts:
            yield p

    return gen()


def test_blob_store_streams_hashes_and_limits(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    with store.temp_file() as tmp:
        got = asyncio.run(store.receive(_chunks(b"hello ", b"world"), tmp, 100))
        assert got.size == 11
        assert got.head == b"hello world"
        store.adopt(tmp, got.sha256)
    assert store.path(got.sha256).read_bytes() == b"hello world"
    assert oct(store.path(got.sha256).stat().st_mode & 0o777) == "0o600"
    with store.temp_file() as tmp, pytest.raises(TooLargeError):
        asyncio.run(store.receive(_chunks(b"x" * 60, b"x" * 60), tmp, 100))
    assert list(store.incoming.iterdir()) == []  # the partial upload is gone
    with pytest.raises(ValueError, match="SHA-256"):
        store.path("../../etc/passwd")


def test_purge_keeps_referenced_and_recent_blobs(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    keep, old, new = store.put(b"keep"), store.put(b"old"), store.put(b"new")
    past = time.time() - 7200
    for sha in (keep, old):
        os.utime(store.path(sha), (past, past))
    assert store.purge({keep}) == 1
    assert store.path(keep).exists()
    assert store.path(new).exists()
    assert not store.path(old).exists()


def test_images_lose_location_but_keep_orientation() -> None:
    cleaned, thumb = asyncio.run(images.clean(jpeg_with_gps(), keep_metadata=False))
    with Image.open(io.BytesIO(cleaned)) as im:
        assert im.format == "JPEG"
        assert im.size == (32, 64)  # rotated upright, then saved without the orientation tag
        assert not im.getexif()
    assert b"Exif" not in cleaned
    with Image.open(io.BytesIO(thumb)) as im:
        assert im.format == "WEBP"


def test_keeping_metadata_keeps_the_original() -> None:
    original = jpeg_with_gps()
    cleaned, _ = asyncio.run(images.clean(original, keep_metadata=True))
    assert cleaned == original


def test_broken_and_hostile_images_are_refused() -> None:
    with pytest.raises(images.ImageError):
        asyncio.run(images.clean(b"\xff\xd8\xff\xe0" + b"\x00" * 100, keep_metadata=False))
    # A decompression bomb: a tiny PNG of 10,000 x 10,000 pixels (over the 50 MP limit).
    out = io.BytesIO()
    Image.new("1", (10_000, 10_000)).save(out, "PNG")
    with pytest.raises(images.ImageError):
        asyncio.run(images.clean(out.getvalue(), keep_metadata=False))

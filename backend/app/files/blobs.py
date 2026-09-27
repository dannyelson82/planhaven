"""Content-addressed blob store under the data directory (ARCHITECTURE.md §10).

Files are named by their SHA-256 (`blobs/ab/cd/<sha256>`), never by anything a user chose,
and live outside every web-served path. Uploads are streamed into `incoming/` first and moved
into place only once complete and accepted.
"""

import contextlib
import hashlib
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHUNK_BYTES = 256 * 1024


class TooLargeError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Received:
    path: Path
    size: int
    sha256: str
    head: bytes


class BlobStore:
    def __init__(self, root: str | Path) -> None:
        self.blobs = Path(root) / "blobs"
        self.incoming = Path(root) / "incoming"

    def _ensure(self) -> None:
        for d in (self.blobs, self.incoming):
            d.mkdir(mode=0o700, parents=True, exist_ok=True)

    def path(self, sha256: str) -> Path:
        if not _SHA256.fullmatch(sha256):
            raise ValueError("not a SHA-256 hex digest")
        return self.blobs / sha256[:2] / sha256[2:4] / sha256

    @contextlib.contextmanager
    def temp_file(self) -> Iterator[Path]:
        """A private temporary file in incoming/; removed afterwards unless moved away."""
        self._ensure()
        path = self.incoming / f"{uuid.uuid4().hex}.part"
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)

    async def receive(self, chunks: AsyncIterator[bytes], dest: Path, max_bytes: int) -> Received:
        """Stream an upload to `dest`, hashing as it goes; stops as soon as it's too big."""
        digest = hashlib.sha256()
        size = 0
        head = b""
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise TooLargeError
                if len(head) < 4096:
                    head += chunk[: 4096 - len(head)]
                digest.update(chunk)
                out.write(chunk)
        return Received(dest, size, digest.hexdigest(), head)

    def adopt(self, source: Path, sha256: str) -> None:
        """Move a completed temporary file into the store under its hash."""
        target = self.path(sha256)
        if target.exists():
            os.utime(target)  # "just used": keeps the purge job away from it
            source.unlink(missing_ok=True)
            return
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(source, 0o600)
        os.replace(source, target)

    def put(self, data: bytes) -> str:
        sha256 = hashlib.sha256(data).hexdigest()
        if self.path(sha256).exists():
            os.utime(self.path(sha256))
            return sha256
        with self.temp_file() as tmp:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as out:
                out.write(data)
            self.adopt(tmp, sha256)
        return sha256

    def purge(self, referenced: set[str], *, min_age_seconds: float = 3600) -> int:
        """Delete blobs nothing refers to (older than `min_age_seconds`, so an upload that
        is being saved right now is never caught), and stale temporary files."""
        now = time.time()
        removed = 0
        if self.blobs.exists():
            for path in self.blobs.glob("*/*/*"):
                if (
                    _SHA256.fullmatch(path.name)
                    and path.name not in referenced
                    and now - path.stat().st_mtime > min_age_seconds
                ):
                    path.unlink(missing_ok=True)
                    removed += 1
        if self.incoming.exists():
            for path in self.incoming.glob("*.part"):
                if now - path.stat().st_mtime > 86400:
                    path.unlink(missing_ok=True)
        return removed

"""Runs the image clean-up process (image_process.py) for uploads (SECURITY.md §7.5, §7.6)."""

import asyncio
import contextlib
import struct
import sys
from pathlib import Path

import app

TIMEOUT_SECONDS = 30
MAX_IMAGE_BYTES = 50 * 1024 * 1024
# At most this many images are decoded at once, so uploads can't use up all memory.
_slots = asyncio.Semaphore(2)
_PACKAGE_ROOT = Path(app.__file__).resolve().parent.parent


class ImageError(Exception):
    pass


def _frames(output: bytes) -> tuple[bytes, bytes]:
    parts: list[bytes] = []
    offset = 0
    for _ in range(2):
        if len(output) < offset + 4:
            raise ImageError("truncated output")
        (length,) = struct.unpack_from(">I", output, offset)
        offset += 4
        if len(output) < offset + length:
            raise ImageError("truncated output")
        parts.append(output[offset : offset + length])
        offset += length
    if offset != len(output):
        raise ImageError("unexpected output")
    return parts[0], parts[1]


async def clean(data: bytes, *, keep_metadata: bool) -> tuple[bytes, bytes]:
    """(cleaned image, WebP thumbnail). Raises ImageError if it isn't a readable image."""
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("image too large")
    args = [sys.executable, "-E", "-s", "-m", "app.files.image_process"]
    if keep_metadata:
        args.append("--keep-metadata")
    async with _slots:
        # Fixed arguments, no shell, empty environment: nothing from the request reaches the
        # command line, and no secrets are inherited.
        process = await asyncio.create_subprocess_exec(  # nosemgrep
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={},
            cwd=_PACKAGE_ROOT,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(data), TIMEOUT_SECONDS)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            raise ImageError("timed out") from None
    if process.returncode != 0:
        raise ImageError("not a readable image")
    return _frames(output)

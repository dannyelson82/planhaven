"""Runs the image clean-up process (image_process.py) for uploads (SECURITY.md §7.5, §7.6)."""

import asyncio
import contextlib
import os
import shutil
import struct
import sys
import tempfile
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


# ------------------------------------------------------------------ HEIC (iPhone photos)
# Pillow can't read HEIC, and the Python packages that can ship a GPL encoder (ADR 0010).
# Debian's libheif decoder is a separate program (allowed as aggregation): it converts the
# photo to JPEG in its own resource-limited process, then the JPEG goes through clean() like
# any other photo (location removed, thumbnail made).
HEIC_TOOLS = ("heif-dec", "heif-convert")  # heif-convert is the older name
_HEIC_LIMITS = [
    "--cpu=20",
    f"--as={1024 * 1024 * 1024}",
    f"--fsize={256 * 1024 * 1024}",
    "--nofile=64",
    "--core=0",
]


def heic_tool() -> str | None:
    for name in HEIC_TOOLS:
        path = shutil.which(name)
        if path:
            return path
    return None


async def heic_to_jpeg(data: bytes, workdir: Path) -> bytes:
    """Decode an iPhone photo to JPEG. Raises ImageError if it can't be read."""
    tool, prlimit = heic_tool(), shutil.which("prlimit")
    if tool is None or prlimit is None:
        raise ImageError("HEIC decoder not installed")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("image too large")
    await asyncio.to_thread(workdir.mkdir, mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        source, target = Path(tmp) / "in.heic", Path(tmp) / "out.jpg"
        await asyncio.to_thread(source.write_bytes, data)
        env = {
            k: v for k, v in os.environ.items() if k in ("LD_LIBRARY_PATH", "LIBHEIF_PLUGIN_PATH")
        }
        async with _slots:
            # Fixed arguments, no shell; the only inputs are our own temporary file names.
            process = await asyncio.create_subprocess_exec(  # nosemgrep
                prlimit,
                *_HEIC_LIMITS,
                "--",
                tool,
                "--quiet",
                "-q",
                "92",
                str(source),
                str(target),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
                cwd=tmp,
            )
            try:
                await asyncio.wait_for(process.wait(), TIMEOUT_SECONDS)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
                raise ImageError("timed out") from None
        # Some photos hold several images (bursts); the decoder then numbers the files.
        outputs = await asyncio.to_thread(lambda: sorted(Path(tmp).glob("out*.jpg")))
        if process.returncode != 0 or not outputs:
            raise ImageError("not a readable HEIC image")
        return await asyncio.to_thread(outputs[0].read_bytes)

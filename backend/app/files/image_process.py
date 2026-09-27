"""Image clean-up in a separate, resource-limited process (SECURITY.md §7.5, §7.6).

Decoding images means running complex parsers on untrusted bytes, so it never happens in the
app process. The app runs `python -m app.files.image_process` with an empty environment; this
process limits its own CPU time, memory, file size and open files *before* reading any input,
then reads the image from stdin and writes back:

    4-byte big-endian length + cleaned image, 4-byte length + thumbnail (WebP)

"Cleaned" means: orientation applied, then re-encoded without EXIF/XMP metadata, so GPS
location is removed. With `--keep-metadata` the original bytes are kept unchanged and only a
thumbnail is made. Exit code 0 on success; anything else means the image was rejected.
"""

import io
import resource
import struct
import sys
import warnings

MAX_PIXELS = 50_000_000  # about 8K x 6K; larger images are refused (decompression bombs)
THUMBNAIL_PX = 480
CPU_SECONDS = 20
MEMORY_BYTES = 1024 * 1024 * 1024
OUTPUT_BYTES = 256 * 1024 * 1024
FORMATS = ("JPEG", "PNG", "GIF", "WEBP")  # only these decoders may run


def _limit() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))  # may not write files
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _frame(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def process(data: bytes, keep_metadata: bool) -> tuple[bytes, bytes]:
    # Imported here, after the limits apply.
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    # Pillow only warns between 1x and 2x the limit; refuse those too.
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    with Image.open(io.BytesIO(data), formats=FORMATS) as original:
        fmt = original.format
        animated = getattr(original, "is_animated", False)
        # Keep the colour profile (phone photos are often Display P3); drop everything else.
        icc = original.info.get("icc_profile")
        colour = {"icc_profile": icc} if isinstance(icc, bytes) and len(icc) < 1_000_000 else {}
        original.load()
        image = ImageOps.exif_transpose(original)

    if keep_metadata:
        cleaned = data
    else:
        out = io.BytesIO()
        if fmt == "JPEG":
            rgb = image if image.mode in ("RGB", "L") else image.convert("RGB")
            rgb.save(out, "JPEG", quality=90, optimize=True, **colour)
        elif fmt == "GIF" and animated:
            # Animated GIFs have no GPS metadata; re-encoding would drop the animation.
            out.write(data)
        else:
            image.save(out, fmt or "PNG", **colour)
        cleaned = out.getvalue()

    thumb = image.copy()
    thumb.thumbnail((THUMBNAIL_PX, THUMBNAIL_PX))
    if thumb.mode not in ("RGB", "RGBA", "L"):
        thumb = thumb.convert("RGBA")
    out = io.BytesIO()
    thumb.save(out, "WEBP", quality=80, **colour)
    return cleaned, out.getvalue()


def main() -> int:
    _limit()
    data = sys.stdin.buffer.read()
    try:
        cleaned, thumbnail = process(data, keep_metadata="--keep-metadata" in sys.argv)
    except Exception:  # any decoder failure means "not a usable image"
        return 2
    sys.stdout.buffer.write(_frame(cleaned) + _frame(thumbnail))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

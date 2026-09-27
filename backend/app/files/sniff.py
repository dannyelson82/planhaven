"""File type detection from the first bytes of a file, never its name (SECURITY.md §7.5).

A small signature table instead of libmagic: fewer parsers on untrusted input, no native
dependency. Anything not recognised is refused.
"""

from dataclasses import dataclass

HEAD_BYTES = 4096


@dataclass(frozen=True, slots=True)
class FileType:
    kind: str  # image | pdf | document | text | model | archive
    mime: str
    extension: str


JPEG = FileType("image", "image/jpeg", "jpg")
PNG = FileType("image", "image/png", "png")
GIF = FileType("image", "image/gif", "gif")
WEBP = FileType("image", "image/webp", "webp")
HEIC = FileType("image", "image/heic", "heic")
PDF = FileType("pdf", "application/pdf", "pdf")
ZIP = FileType("archive", "application/zip", "zip")
OLE = FileType("document", "application/x-ole-storage", "doc")  # legacy .doc/.xls
TEXT = FileType("text", "text/plain", "txt")
STL = FileType("model", "model/stl", "stl")

# Office Open XML and OpenDocument files are ZIP containers; keep their own names and types
# when the ZIP's name says so. They're stored and downloaded, never opened by the server.
_ZIP_DOCUMENTS = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "3mf": "model/3mf",
}
_OLE_DOCUMENTS = {"doc": "application/msword", "xls": "application/vnd.ms-excel"}
_TEXT_TYPES = {
    "csv": "text/csv",
    "md": "text/markdown",
    "txt": "text/plain",
    "dxf": "image/vnd.dxf",
    "gcode": "text/x-gcode",
    "json": "application/json",
}


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _is_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A multi-byte character cut off at the end of the sample is still text.
        return exc.start >= len(head) - 3
    return True


def detect(head: bytes, filename: str, size: int) -> FileType | None:
    """The file's type, or None when it isn't on the allowlist."""
    ext = _extension(filename)
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return GIF
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
        return HEIC
    if head.startswith(b"%PDF-"):
        return PDF
    if head.startswith(b"PK\x03\x04"):
        if ext in _ZIP_DOCUMENTS:
            kind = "model" if ext == "3mf" else "document"
            return FileType(kind, _ZIP_DOCUMENTS[ext], ext)
        return ZIP
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return FileType("document", _OLE_DOCUMENTS[ext], ext) if ext in _OLE_DOCUMENTS else OLE
    if ext == "stl" and len(head) >= 84:
        # Binary STL: 80-byte header, triangle count, 50 bytes per triangle.
        triangles = int.from_bytes(head[80:84], "little")
        if size == 84 + 50 * triangles:
            return STL
    if _is_text(head):
        if ext == "stl" and head.lstrip().startswith(b"solid"):
            return STL
        if ext in _TEXT_TYPES:
            return FileType("text", _TEXT_TYPES[ext], ext)
        return TEXT
    return None


def safe_filename(filename: str, file_type: FileType) -> str:
    """A display name for the file: no path, no control characters, a matching extension."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '"<>|:*?').strip(" .")
    stem = name.rsplit(".", 1)[0] if "." in name else name
    stem = stem[:200] or "file"
    return f"{stem}.{file_type.extension}"

"""Contact cards (vCard, .vcf): reading one shared from a phone, and writing one to save to it.

The card is untrusted input, read by this small parser with limits rather than a library:
- size (MAX_BYTES) and line count are capped; only the first card in the file is used;
- only the fields PlanHaven keeps are read (name, organization, phone, email, website, note,
  photo); everything else is ignored;
- a website is kept only if it's http(s) (a bare "www.example.com" gets https://);
- an embedded photo is decoded (base64, capped) and then cleaned like any upload by the
  caller; a photo given as a link is never fetched.
Versions 2.1, 3.0 and 4.0 are understood, including folded lines and quoted-printable text.
"""

import base64
import binascii
import quopri
import re
from dataclasses import dataclass

MAX_BYTES = 3 * 1024 * 1024
MAX_LINES = 5000
MAX_PHOTO_BYTES = 2 * 1024 * 1024


class VCardError(ValueError):
    """Not a contact card PlanHaven can read (message is safe to show)."""


@dataclass(frozen=True, slots=True)
class Card:
    name: str
    company: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    notes: str = ""
    photo: bytes | None = None


_WEBSITE = re.compile(r"^(https?://)?[^\s/:]+\.[^\s]+$", re.IGNORECASE)


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif lines and lines[-1].endswith("=") and "QUOTED-PRINTABLE" in lines[-1].upper():
            lines[-1] = lines[-1][:-1] + raw  # quoted-printable soft line break (2.1)
        else:
            lines.append(raw)
        if len(lines) > MAX_LINES:
            raise VCardError("This contact card is too long.")
    return lines


def _unescape(value: str) -> str:
    out = []
    i = 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _split_unescaped(value: str, sep: str) -> list[str]:
    parts, current, i = [], [], 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            current.append(value[i : i + 2])
            i += 2
            continue
        if value[i] == sep:
            parts.append("".join(current))
            current = []
        else:
            current.append(value[i])
        i += 1
    parts.append("".join(current))
    return parts


def _parse_line(line: str) -> tuple[str, dict[str, str], str] | None:
    if ":" not in line:
        return None
    head, value = line.split(":", 1)
    name, *params = head.split(";")
    name = name.split(".")[-1].upper()  # "item1.TEL" -> "TEL"
    options: dict[str, str] = {}
    for p in params:
        key, _, val = p.partition("=")
        options[key.upper()] = val.strip('"') if val else key.upper()  # 2.1: ";JPEG"
    return name, options, value


def _text(options: dict[str, str], value: str) -> str:
    if options.get("ENCODING", "").upper() == "QUOTED-PRINTABLE":
        charset = options.get("CHARSET", "utf-8")
        try:
            value = quopri.decodestring(value.encode("ascii", "replace")).decode(charset, "replace")
        except LookupError:
            value = quopri.decodestring(value.encode("ascii", "replace")).decode("utf-8", "replace")
    return _unescape(value).strip()


def _photo(options: dict[str, str], value: str) -> bytes | None:
    data = value.strip()
    if data.lower().startswith("data:"):  # 4.0: data:image/jpeg;base64,....
        header, _, data = data.partition(",")
        if ";base64" not in header.lower():
            return None
    elif options.get("ENCODING", "").upper() not in ("B", "BASE64"):
        return None  # a link (never fetched), or something else
    if len(data) > MAX_PHOTO_BYTES * 4 // 3 + 16:
        return None
    try:
        return base64.b64decode(re.sub(r"\s", "", data), validate=True)
    except binascii.Error, ValueError:
        return None


def parse(data: bytes) -> Card:
    """The first contact card in `data`."""
    if len(data) > MAX_BYTES:
        raise VCardError("This contact card is too large.")
    text = data.decode("utf-8", "replace").lstrip("﻿")
    fields: dict[str, str] = {}
    photo: bytes | None = None
    inside = False
    for line in _unfold(text):
        parsed = _parse_line(line)
        if parsed is None:
            continue
        name, options, value = parsed
        if name == "BEGIN" and value.strip().upper() == "VCARD":
            inside = True
            continue
        if name == "END" and value.strip().upper() == "VCARD" and inside:
            break
        if not inside:
            continue
        if name == "PHOTO" and photo is None:
            photo = _photo(options, value)
        elif name == "N" and "N" not in fields:
            family, given, *_ = [*_split_unescaped(value, ";"), "", ""]
            fields["N"] = " ".join(p for p in (_text(options, given), _text(options, family)) if p)
        elif name == "ORG" and "ORG" not in fields:
            fields["ORG"] = " ".join(
                p for p in (_text(options, x) for x in _split_unescaped(value, ";")) if p
            )
        elif name in ("FN", "TEL", "EMAIL", "URL", "NOTE") and name not in fields:
            fields[name] = _text(options, value)
    if not inside:
        raise VCardError("This file isn't a contact card.")
    name = fields.get("FN") or fields.get("N") or fields.get("ORG") or ""
    if not name:
        raise VCardError("This contact card has no name.")
    website = fields.get("URL", "")
    if website.lower().startswith("http:") or website.lower().startswith("https:"):
        website = website if _WEBSITE.match(website) else ""
    elif website and _WEBSITE.match(website):
        website = f"https://{website}"
    else:
        website = ""
    return Card(
        name=name[:200],
        company=fields.get("ORG", "")[:200] if fields.get("ORG") != name else "",
        phone=fields.get("TEL", "").removeprefix("tel:")[:50],
        email=fields.get("EMAIL", "").removeprefix("mailto:")[:254],
        website=website[:500],
        notes=fields.get("NOTE", "")[:20000],
        photo=photo,
    )


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> list[str]:
    """Lines of at most 75 octets, continued with a leading space (RFC 6350)."""
    out, current = [], ""
    for ch in line:
        if len((current + ch).encode()) > 75:
            out.append(current)
            current = " " + ch
        else:
            current += ch
    out.append(current)
    return out


def build(card: Card, photo_type: str | None = None) -> str:
    """A vCard 3.0 for one contact (iPhone and Android both import 3.0)."""
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{_escape(card.name)}"]
    given, _, family = card.name.rpartition(" ")
    lines.append(f"N:{_escape(family if given else card.name)};{_escape(given)};;;")
    if card.company:
        lines.append(f"ORG:{_escape(card.company)}")
    if card.phone:
        lines.append(f"TEL;TYPE=CELL:{_escape(card.phone)}")
    if card.email:
        lines.append(f"EMAIL;TYPE=INTERNET:{_escape(card.email)}")
    if card.website:
        lines.append(f"URL:{_escape(card.website)}")
    if card.notes:
        lines.append(f"NOTE:{_escape(card.notes)}")
    if card.photo:
        kind = "PNG" if photo_type == "image/png" else "JPEG"
        lines.append(f"PHOTO;ENCODING=b;TYPE={kind}:{base64.b64encode(card.photo).decode()}")
    lines.append("END:VCARD")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"

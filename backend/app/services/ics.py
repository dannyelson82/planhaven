"""Writing an iCalendar (RFC 5545) feed: escaping, line folding, all-day and timed events.
No dependency: the feed only needs VEVENTs with a few properties."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta


@dataclass(frozen=True, slots=True)
class Event:
    uid: str
    summary: str
    start: datetime | date  # a date: an all-day event
    description: str = ""
    stamp: datetime | None = None


def escape(value: str) -> str:
    """TEXT escaping (RFC 5545 §3.3.11); control characters dropped."""
    value = "".join(c for c in value if c in "\n\t" or ord(c) >= 32)
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Lines longer than 75 octets continue on the next line after a space (§3.1), never
    splitting a UTF-8 character."""
    out: list[str] = []
    current = ""
    size = 0
    for ch in line:
        n = len(ch.encode())
        if size + n > (75 if not out else 74):
            out.append(current)
            current, size = "", 0
        current += ch
        size += n
    out.append(current)
    return "\r\n ".join(out)


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def calendar(name: str, events: list[Event], now: datetime | None = None) -> str:
    stamp = now or datetime.now(UTC)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PlanHaven//Calendar feed//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape(name)}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for e in events:
        lines += ["BEGIN:VEVENT", f"UID:{escape(e.uid)}", f"DTSTAMP:{_utc(e.stamp or stamp)}"]
        if isinstance(e.start, datetime):
            lines += [f"DTSTART:{_utc(e.start)}", f"DTEND:{_utc(e.start + timedelta(minutes=30))}"]
        else:
            following = e.start + timedelta(days=1)
            lines += [
                f"DTSTART;VALUE=DATE:{e.start:%Y%m%d}",
                f"DTEND;VALUE=DATE:{following:%Y%m%d}",
            ]
        lines.append(f"SUMMARY:{escape(e.summary)}")
        if e.description:
            lines.append(f"DESCRIPTION:{escape(e.description)}")
        lines += ["TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"

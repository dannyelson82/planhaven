"""The calendar feed format (RFC 5545), without a database."""

from datetime import UTC, date, datetime

from app.services import ics


def test_escaping_and_folding() -> None:
    assert ics.escape("Oil; filter, 5W-30\\new\nline") == r"Oil\; filter\, 5W-30\\new\nline"
    assert ics.escape("bell\x07") == "bell"
    line = "SUMMARY:" + "é" * 100
    folded = ics.fold(line)
    assert all(len(part.encode()) <= 75 for part in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == line


def test_events() -> None:
    now = datetime(2026, 10, 2, 12, tzinfo=UTC)
    body = ics.calendar(
        "PlanHaven",
        [
            ics.Event(
                "task-1@planhaven", "Chore: Bins out · Home", datetime(2026, 10, 6, 23, tzinfo=UTC)
            ),
            ics.Event("service-2@planhaven", "Service: Oil · Boat", date(2026, 11, 1), "5 quarts"),
        ],
        now,
    )
    lines = body.split("\r\n")
    assert (lines[0], lines[-2]) == ("BEGIN:VCALENDAR", "END:VCALENDAR")
    for expected in (
        "DTSTART:20261006T230000Z",
        "DTEND:20261006T233000Z",
        "DTSTART;VALUE=DATE:20261101",
        "DTEND;VALUE=DATE:20261102",
    ):
        assert expected in lines
    assert "SUMMARY:Chore: Bins out · Home" in lines
    assert "DESCRIPTION:5 quarts" in lines
    assert body.endswith("\r\n")

"""When a scheduled service is due (no database)."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from app.services.asset_service import RecordRow, ScheduleRow, add_months, due

A = uuid.uuid7()


def _schedule(
    every_distance: Decimal | None = None,
    every_hours: Decimal | None = None,
    every_months: int | None = None,
) -> ScheduleRow:
    return ScheduleRow(
        id=uuid.uuid7(),
        asset_id=A,
        name="Oil",
        every_distance=every_distance,
        every_hours=every_hours,
        every_months=every_months,
        notes="",
        version=1,
    )


def _done(day: date, distance: str | None = None, hours: str | None = None) -> RecordRow:
    return RecordRow(
        id=uuid.uuid7(),
        asset_id=A,
        schedule_id=None,
        title="Oil",
        done_on=day,
        distance=Decimal(distance) if distance else None,
        hours=Decimal(hours) if hours else None,
        cost_cents=None,
        notes="",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_add_months_keeps_the_day_or_the_months_end() -> None:
    assert add_months(date(2026, 1, 15), 12) == date(2027, 1, 15)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_never_done_is_unknown() -> None:
    d = due(_schedule(every_months=12), None, distance=None, hours=None, today=date(2026, 10, 2))
    assert d.status == "unknown"


def test_whichever_comes_first() -> None:
    s = _schedule(every_distance=Decimal("8000"), every_months=12)
    last = _done(date(2026, 1, 10), distance="50000")
    today = date(2026, 6, 1)
    ok = due(s, last, distance=Decimal("52000"), hours=None, today=today)
    assert (ok.status, ok.due_on, ok.due_distance) == ("ok", date(2027, 1, 10), Decimal("58000"))
    # Distance first: within the last tenth is soon, at or past it is overdue.
    assert due(s, last, distance=Decimal("57300"), hours=None, today=today).status == "soon"
    assert due(s, last, distance=Decimal("58000"), hours=None, today=today).status == "overdue"
    # Time first: 30 days before is soon, the day itself is overdue.
    assert due(s, last, distance=None, hours=None, today=date(2026, 12, 15)).status == "soon"
    assert due(s, last, distance=None, hours=None, today=date(2027, 1, 10)).status == "overdue"


def test_hours() -> None:
    s = _schedule(every_hours=Decimal("100"))
    last = _done(date(2026, 5, 1), hours="400")
    assert due(s, last, distance=None, hours=Decimal("450"), today=date(2026, 6, 1)).status == "ok"
    assert due(s, last, distance=None, hours=Decimal("500.5"), today=date(2026, 6, 1)).status == (
        "overdue"
    )


def test_distance_schedule_without_a_recorded_distance_is_unknown() -> None:
    s = _schedule(every_distance=Decimal("8000"))
    d = due(s, _done(date(2026, 5, 1)), distance=Decimal("1"), hours=None, today=date(2026, 6, 1))
    assert d.status == "unknown"

"""Chores without a database: when a repeating chore is next due, and who may do what."""

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app import authz
from app.services.chores import next_due

TZ = ZoneInfo("America/Toronto")
P = authz.Principal(uuid.uuid4(), False, True, None)


def _local(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def test_daily_and_monthly_keep_the_time_of_day() -> None:
    due = _local(2026, 10, 2, 19, 0)
    assert next_due(due, "daily", 1, None, TZ, due) == _local(2026, 10, 3, 19, 0)
    assert next_due(due, "daily", 2, None, TZ, due) == _local(2026, 10, 4, 19, 0)
    jan31 = _local(2026, 1, 31, 8, 0)
    assert next_due(jan31, "monthly", 1, None, TZ, jan31) == _local(2026, 2, 28, 8, 0)
    # Across the clock change (Nov 1): still 7 pm local.
    assert next_due(
        _local(2026, 10, 31, 19), "daily", 1, None, TZ, _local(2026, 10, 31, 19)
    ) == _local(2026, 11, 1, 19)


def test_weekly_on_chosen_days_and_every_other_week() -> None:
    tuesday = _local(2026, 10, 6, 19, 0)  # 0 = Sunday ... 2 = Tuesday, 5 = Friday
    assert next_due(tuesday, "weekly", 1, [2], TZ, tuesday) == _local(2026, 10, 13, 19, 0)
    assert next_due(tuesday, "weekly", 1, [2, 5], TZ, tuesday) == _local(2026, 10, 9, 19, 0)
    assert next_due(tuesday, "weekly", 2, [2], TZ, tuesday) == _local(2026, 10, 20, 19, 0)
    assert next_due(tuesday, "weekly", 1, None, TZ, tuesday) == _local(2026, 10, 13, 19, 0)


def test_missed_times_are_skipped() -> None:
    long_ago = _local(2026, 1, 6, 19, 0)
    now = datetime(2026, 10, 2, 12, tzinfo=UTC)
    assert next_due(long_ago, "weekly", 1, [2], TZ, now) == _local(2026, 10, 6, 19, 0)


@pytest.mark.parametrize(
    ("access", "action", "outcome"),
    [
        (authz.ChoreAccess(True, False, None), authz.Action.CHORE_VIEW, None),
        (authz.ChoreAccess(True, False, None), authz.Action.CHORE_COMPLETE, None),
        (authz.ChoreAccess(True, False, None), authz.Action.CHORE_REVIEW, authz.ForbiddenError),
        (authz.ChoreAccess(False, True, "editor"), authz.Action.CHORE_REVIEW, None),
        (authz.ChoreAccess(False, False, "editor"), authz.Action.CHORE_REVIEW, None),
        (
            authz.ChoreAccess(False, False, "viewer"),
            authz.Action.CHORE_REVIEW,
            authz.ForbiddenError,
        ),
        (
            authz.ChoreAccess(False, False, "owner"),
            authz.Action.CHORE_COMPLETE,
            authz.ForbiddenError,
        ),
        (authz.ChoreAccess(False, False, None), authz.Action.CHORE_VIEW, authz.NotFoundError),
    ],
)
def test_who_may_do_what(
    access: authz.ChoreAccess, action: authz.Action, outcome: type[Exception] | None
) -> None:
    if outcome is None:
        authz.require_chore(P, action, access)
    else:
        with pytest.raises(outcome):
            authz.require_chore(P, action, access)

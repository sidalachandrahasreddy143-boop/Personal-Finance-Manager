"""Calendar / period arithmetic tests - pure functions, no database."""

from __future__ import annotations

import datetime as dt

import pytest

from app.models.enums import BudgetPeriod, Frequency
from app.services.periods import (
    add_frequency,
    add_months,
    default_range,
    month_end,
    month_sequence,
    month_start,
    period_end_for,
    period_start_for,
    previous_window,
)


def test_month_start_and_end() -> None:
    assert month_start(dt.date(2026, 2, 14)) == dt.date(2026, 2, 1)
    assert month_end(dt.date(2026, 2, 14)) == dt.date(2026, 2, 28)
    assert month_end(dt.date(2024, 2, 14)) == dt.date(2024, 2, 29)  # leap year


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (dt.date(2026, 1, 31), 1, dt.date(2026, 2, 28)),  # clamps to short month
        (dt.date(2026, 1, 15), 1, dt.date(2026, 2, 15)),
        (dt.date(2026, 11, 30), 3, dt.date(2027, 2, 28)),  # crosses the year
        (dt.date(2026, 3, 31), -1, dt.date(2026, 2, 28)),
        (dt.date(2024, 2, 29), 12, dt.date(2025, 2, 28)),
    ],
)
def test_add_months_clamps_and_rolls_over(start: dt.date, months: int, expected: dt.date) -> None:
    assert add_months(start, months) == expected


def test_period_bounds_for_each_budget_period() -> None:
    mid_week = dt.date(2026, 9, 16)  # a Wednesday
    assert period_start_for(BudgetPeriod.WEEKLY, mid_week) == dt.date(2026, 9, 14)  # Monday
    assert period_end_for(BudgetPeriod.WEEKLY, dt.date(2026, 9, 14)) == dt.date(2026, 9, 20)

    assert period_start_for(BudgetPeriod.MONTHLY, mid_week) == dt.date(2026, 9, 1)
    assert period_end_for(BudgetPeriod.MONTHLY, dt.date(2026, 9, 1)) == dt.date(2026, 9, 30)

    assert period_start_for(BudgetPeriod.YEARLY, mid_week) == dt.date(2026, 1, 1)
    assert period_end_for(BudgetPeriod.YEARLY, dt.date(2026, 1, 1)) == dt.date(2026, 12, 31)


def test_previous_window_is_equal_length() -> None:
    start, end = previous_window(dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert (end - start).days == 29
    assert end == dt.date(2026, 8, 31)
    assert start == dt.date(2026, 8, 2)


@pytest.mark.parametrize(
    ("frequency", "interval", "expected"),
    [
        (Frequency.DAILY, 3, dt.date(2026, 9, 4)),
        (Frequency.WEEKLY, 2, dt.date(2026, 9, 15)),
        (Frequency.MONTHLY, 1, dt.date(2026, 10, 1)),
        (Frequency.YEARLY, 1, dt.date(2027, 9, 1)),
    ],
)
def test_add_frequency(frequency: Frequency, interval: int, expected: dt.date) -> None:
    assert add_frequency(dt.date(2026, 9, 1), frequency, interval) == expected


def test_default_range_covers_requested_days() -> None:
    start, end = default_range(30, as_of=dt.date(2026, 9, 30))
    assert (end - start).days == 29  # inclusive of both ends
    assert end == dt.date(2026, 9, 30)


def test_month_sequence_includes_gaps_and_year_boundaries() -> None:
    assert month_sequence(dt.date(2026, 11, 5), dt.date(2027, 2, 1)) == [
        "2026-11",
        "2026-12",
        "2027-01",
        "2027-02",
    ]

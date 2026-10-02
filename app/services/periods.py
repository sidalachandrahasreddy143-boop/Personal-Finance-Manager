"""Calendar maths used by budgets, reports and recurring rules.

Pure functions - no I/O - which makes them trivial to unit test and reuse.
"""

from __future__ import annotations

import calendar
import datetime as dt

from app.models.enums import BudgetPeriod, Frequency


def today_utc() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


def month_start(value: dt.date) -> dt.date:
    return value.replace(day=1)


def month_end(value: dt.date) -> dt.date:
    last_day = calendar.monthrange(value.year, value.month)[1]
    return value.replace(day=last_day)


def add_months(value: dt.date, months: int) -> dt.date:
    """Shift a date by N months, clamping to the length of the target month."""
    total = value.month - 1 + months
    year = value.year + total // 12
    month = total % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def period_start_for(period: BudgetPeriod, on_date: dt.date) -> dt.date:
    """First day of the budget window containing ``on_date``."""
    if period is BudgetPeriod.WEEKLY:
        return on_date - dt.timedelta(days=on_date.weekday())
    if period is BudgetPeriod.YEARLY:
        return on_date.replace(month=1, day=1)
    return month_start(on_date)


def period_end_for(period: BudgetPeriod, start: dt.date) -> dt.date:
    """Inclusive last day of the window starting at ``start``."""
    if period is BudgetPeriod.WEEKLY:
        return start + dt.timedelta(days=6)
    if period is BudgetPeriod.YEARLY:
        return start.replace(month=12, day=31)
    return month_end(start)


def previous_window(date_from: dt.date, date_to: dt.date) -> tuple[dt.date, dt.date]:
    """The equally-long window immediately before ``[date_from, date_to]``."""
    span = (date_to - date_from).days + 1
    return date_from - dt.timedelta(days=span), date_from - dt.timedelta(days=1)


def add_frequency(value: dt.date, frequency: Frequency, interval: int = 1) -> dt.date:
    """Advance a date by ``interval`` units of ``frequency``."""
    interval = max(1, interval)
    if frequency is Frequency.DAILY:
        return value + dt.timedelta(days=interval)
    if frequency is Frequency.WEEKLY:
        return value + dt.timedelta(weeks=interval)
    if frequency is Frequency.MONTHLY:
        return add_months(value, interval)
    return value.replace(year=value.year + interval)


def default_range(days: int = 90, *, as_of: dt.date | None = None) -> tuple[dt.date, dt.date]:
    """Default reporting window: the last ``days`` days ending today."""
    end = as_of or today_utc()
    return end - dt.timedelta(days=days - 1), end


def month_sequence(date_from: dt.date, date_to: dt.date) -> list[str]:
    """Every ``YYYY-MM`` bucket between two dates, gaps included."""
    buckets: list[str] = []
    cursor = month_start(date_from)
    while cursor <= date_to:
        buckets.append(cursor.strftime("%Y-%m"))
        cursor = add_months(cursor, 1)
    return buckets

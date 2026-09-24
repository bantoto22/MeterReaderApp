"""Billing policy mirrored from the authenticated assigned-consumer API."""

from __future__ import annotations

from datetime import date, datetime, timedelta


DEFAULT_DUE_DAYS = 15
DEFAULT_LATE_FEE_PERCENT = 10.0


def due_days(value: object) -> int:
    """Use the cached API value, or the legacy default when it is absent."""
    try:
        return max(0, int(value)) if value not in (None, "") else DEFAULT_DUE_DAYS
    except (TypeError, ValueError):
        return DEFAULT_DUE_DAYS


def late_fee_percent(value: object) -> float:
    try:
        return max(0.0, float(value)) if value not in (None, "") else DEFAULT_LATE_FEE_PERCENT
    except (TypeError, ValueError):
        return DEFAULT_LATE_FEE_PERCENT


def payment_due_date(reading_date: date | datetime | str, configured_due_days: object) -> date:
    if isinstance(reading_date, datetime):
        reading_day = reading_date.date()
    elif isinstance(reading_date, date):
        reading_day = reading_date
    else:
        reading_day = date.fromisoformat(str(reading_date)[:10])
    due = reading_day + timedelta(days=due_days(configured_due_days))
    if due.weekday() == 5:  # Saturday: pay by Friday.
        due -= timedelta(days=1)
    elif due.weekday() == 6:  # Sunday: pay on Monday.
        due += timedelta(days=1)
    return due

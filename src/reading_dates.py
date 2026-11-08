"""Dates belonging to the meter readings, independent of billing schedules."""

from datetime import date


def scheduled_coverage(source: dict, schedule_date=None) -> tuple[str | None, str | None]:
    """Use synchronized coverage or an immutable queued snapshot; never guess a month."""
    def valid(value):
        try:
            return date.fromisoformat(str(value or '').split('T', 1)[0].split(' ', 1)[0]).isoformat()
        except ValueError:
            return None
    start = valid(source.get('coverage_from') or source.get('previous_schedule_date'))
    end = valid(schedule_date or source.get('schedule_date') or source.get('coverage_to'))
    if start and end and start > end:
        return None, end
    return start, end


def previous_reading_date(source: dict) -> str | None:
    for key in ("previous_reading_date", "last_reading_date", "latest_reading_date"):
        value = str(source.get(key) or "").strip().split("T", 1)[0].split(" ", 1)[0]
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            # An explicit snapshot (including an unknown date) must survive
            # later saves that change the consumer's latest reading date.
            if key == "previous_reading_date" and key in source:
                return None
    return None

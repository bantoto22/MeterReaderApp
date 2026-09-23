"""Dates belonging to the meter readings, independent of billing schedules."""

from datetime import date


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

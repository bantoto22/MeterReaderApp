"""Prefer a reader's full name, falling back to their login username."""


def reader_display_name(user: dict | None) -> str:
    user = user or {}
    username = str(user.get("username") or "").strip()
    for key in ("full_name", "fullName", "Full_Name", "name"):
        value = str(user.get(key) or "").strip()
        if value and value.casefold() not in {username.casefold(), "field reader", "user", "n/a"}:
            return value
    parts = [
        str(user.get(snake) or user.get(camel) or "").strip()
        for snake, camel in (
            ("first_name", "firstName"),
            ("middle_name", "middleName"),
            ("last_name", "lastName"),
        )
    ]
    return " ".join(part for part in parts if part) or username

"""Preview or remove old unused local reservations, with a verified SQLite backup.

Close the device app first. This standalone command has no network dependency and
does not release backend reservations or reuse their reference numbers.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import uuid


REQUIRED_COLUMNS = {
    "local_billing_reference_reservations": {
        "bill_sync_id", "reading_sync_id", "bill_date", "billing_reference", "status", "bill_id", "used_at",
    },
    "sync_queue_meter_readings": {"reading_id", "payload", "server_payload"},
    "readings": {"sync_reading_id"},
    "receipt_prints": {"receipt_text"},
    "handheld_consumer_context_cache": {"context_json"},
    "handheld_consumers_cache": {"billing_reference"},
}
OPTIONAL_TABLES = {"handheld_consumer_context_cache"}  # Absent in older device versions.


def _verify_schema(connection: sqlite3.Connection) -> set[str]:
    available: set[str] = set()
    for table, required in REQUIRED_COLUMNS.items():
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if not columns and table in OPTIONAL_TABLES:
            continue
        if not required <= columns:
            raise ValueError(f"Cannot safely inspect {table}: required columns are missing. No references removed.")
        available.add(table)
    return available


def _add_tokens(value, protected: set[str]) -> None:
    if isinstance(value, dict):
        for nested in value.values():
            _add_tokens(nested, protected)
    elif isinstance(value, list):
        for nested in value:
            _add_tokens(nested, protected)
    elif isinstance(value, str) and value.strip():
        protected.add(value.strip().lower())


def _add_json_tokens(raw, table: str, protected: set[str]) -> None:
    if raw in (None, ""):
        return
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Cannot safely inspect invalid JSON in {table}. No references removed.") from exc
    _add_tokens(value, protected)


def _plan(connection: sqlite3.Connection, today: date) -> tuple[dict, dict[str, dict]]:
    available = _verify_schema(connection)
    protected: set[str] = set()
    for row in connection.execute("SELECT reading_id, payload, server_payload FROM sync_queue_meter_readings"):
        _add_tokens(row["reading_id"], protected)
        _add_json_tokens(row["payload"], "sync_queue_meter_readings", protected)
        _add_json_tokens(row["server_payload"], "sync_queue_meter_readings", protected)
    for row in connection.execute("SELECT sync_reading_id FROM readings"):
        _add_tokens(row["sync_reading_id"], protected)
    if "handheld_consumer_context_cache" in available:
        for row in connection.execute("SELECT context_json FROM handheld_consumer_context_cache"):
            _add_json_tokens(row["context_json"], "handheld_consumer_context_cache", protected)
    for row in connection.execute("SELECT billing_reference FROM handheld_consumers_cache"):
        _add_tokens(row["billing_reference"], protected)
    receipts = [str(row["receipt_text"] or "").lower()
                for row in connection.execute("SELECT receipt_text FROM receipt_prints")]
    reservations = [dict(row) for row in connection.execute("SELECT * FROM local_billing_reference_reservations")]

    def keys(row: dict) -> list[str]:
        return [str(row.get(key) or "").strip().lower()
                for key in ("bill_sync_id", "reading_sync_id", "billing_reference") if row.get(key)]

    def unused(row: dict) -> bool:
        return (row["status"] in {"Pending", "Reserved"}
                and row["bill_id"] is None and row["used_at"] is None)

    # Also protect an inconsistent second reservation that shares an issued ID/reference.
    for row in reservations:
        if not unused(row):
            protected.update(keys(row))
    eligible: dict[str, dict] = {}
    kept: Counter = Counter()
    for row in reservations:
        try:
            bill_date = date.fromisoformat(str(row["bill_date"]))
        except (TypeError, ValueError):
            kept["invalid_date"] += 1
            continue
        if bill_date >= today:
            kept["current_or_future_date"] += 1
        elif not unused(row):
            kept["used_or_other_status"] += 1
        elif any(key in protected or any(key in text for text in receipts) for key in keys(row)):
            kept["linked_to_saved_work"] += 1
        else:
            eligible[row["bill_sync_id"]] = row
    return ({"cutoff_date": today.isoformat(), "total_reservations": len(reservations),
             "eligible_old_unused": len(eligible), "kept_by_reason": dict(kept)}, eligible)


def cleanup_offline_references(db_path: str | Path, *, apply: bool = False, today: date | None = None) -> dict:
    path = Path(db_path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("The database path must identify an existing file.")
    cutoff = today or datetime.now(timezone(timedelta(hours=8))).date()
    mode = "rw" if apply else "ro"
    connection = sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN")
        report, eligible = _plan(connection, cutoff)
        connection.rollback()
        report.update({"database": str(path), "applied": apply, "removed": 0, "backup": None})
        if not apply or not eligible:
            return report

        backup_directory = path.parent / "backups"
        backup_directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
        backup_path = backup_directory / f"{path.stem}-before-reference-cleanup-{stamp}-{uuid.uuid4().hex[:8]}.db"
        backup = sqlite3.connect(backup_path)
        try:
            backup.row_factory = sqlite3.Row
            connection.backup(backup)
            if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("The database backup could not be verified. No references removed.")
            _, backed_up = _plan(backup, cutoff)
        finally:
            backup.close()

        # Recheck links under a write lock. Only delete unchanged records present
        # in the backup, so racing writes cannot turn an eligible draft into lost work.
        connection.execute("BEGIN IMMEDIATE")
        current_report, current = _plan(connection, cutoff)
        remove_ids = [key for key, row in current.items() if backed_up.get(key) == row]
        cursor = connection.executemany(
            "DELETE FROM local_billing_reference_reservations WHERE bill_sync_id = ?",
            [(key,) for key in remove_ids],
        )
        if cursor.rowcount != len(remove_ids):
            raise ValueError("Cleanup counts did not reconcile; changes rolled back.")
        remaining = connection.execute("SELECT COUNT(*) FROM local_billing_reference_reservations").fetchone()[0]
        if remaining != current_report["total_reservations"] - len(remove_ids):
            raise ValueError("Reservation totals did not reconcile; changes rolled back.")
        audit_columns = {row["name"] for row in connection.execute("PRAGMA table_info(sync_audit_log)")}
        if remove_ids and {"queue_id", "status", "message", "payload"} <= audit_columns:
            connection.execute(
                "INSERT INTO sync_audit_log (queue_id, status, message, payload) VALUES (NULL, ?, ?, ?)",
                ("maintenance", f"Removed {len(remove_ids)} old unused offline reference reservations.",
                 json.dumps({"removed": len(remove_ids), "cutoff_date": cutoff.isoformat(), "backup": str(backup_path)})),
            )
        connection.commit()
        report.update(current_report)
        report.update({"removed": len(remove_ids), "backup": str(backup_path),
                       "deferred_changed_records": len(current) - len(remove_ids), "remaining_reservations": remaining})
        return report
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "meter.db")
    parser.add_argument("--apply", action="store_true", help="Back up the database and remove only old unused reservations.")
    args = parser.parse_args(argv)
    try:
        report = cleanup_offline_references(args.db, apply=args.apply)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Cleanup stopped: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

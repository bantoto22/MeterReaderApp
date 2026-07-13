"""
Handheld sync layer for online/offline meter reading operations.

Online:
- Reads/writes via Supabase REST.

Offline:
- Writes are queued in local SQLite on the Pi.
- Reads use local cached consumers/meters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import uuid
from urllib import error, parse, request

sqlite3.register_adapter(Decimal, float)

SYNC_BATCH_SIZE = 100
BACKGROUND_SYNC_INTERVAL_SECONDS = 300

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False


def _load_env_fallback(env_path: str) -> None:
    """Simple .env loader fallback when python-dotenv is unavailable."""
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        pass
    raw = raw.split("T", 1)[0].split(" ", 1)[0]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        d = _parse_date(raw)
        return datetime.combine(d, datetime.min.time()) if d else None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _reading_date(value) -> date:
    parsed = _parse_date(value)
    return parsed or datetime.now().date()


def _device_schedule_window(today: date | None = None) -> tuple[str, str]:
    anchor = today or datetime.now().date()
    start = anchor.replace(day=1)
    year = start.year + ((start.month) // 12)
    month = 1 if start.month == 12 else start.month + 1
    next_month_start = date(year, month, 1)
    following_year = next_month_start.year + ((next_month_start.month) // 12)
    following_month = 1 if next_month_start.month == 12 else next_month_start.month + 1
    following_start = date(following_year, following_month, 1)
    end = following_start - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _verify_password(candidate_password: str, stored_password: str | None) -> bool:
    candidate = str(candidate_password or "")
    stored = str(stored_password or "")
    if not stored:
        return False
    if stored == candidate:
        return True
    if stored.startswith("scrypt$"):
        parts = stored.split("$", 2)
        if len(parts) != 3:
            return False
        _, salt_hex, expected_hex = parts
        try:
            derived = hashlib.scrypt(
                candidate.encode("utf-8"),
                salt=bytes.fromhex(salt_hex),
                n=16384,
                r=8,
                p=1,
                dklen=len(bytes.fromhex(expected_hex)),
            )
            return hmac.compare_digest(derived.hex(), expected_hex.lower())
        except Exception:
            return False
    return False


def _compute_charge(consumption: int, minimum_cubic, minimum_rate, excess_rate_per_cubic) -> float:
    safe_consumption = max(consumption, 0)
    minimum_cubic_int = _safe_int(minimum_cubic)
    minimum_rate_val = _safe_float(minimum_rate)
    excess_rate_val = _safe_float(excess_rate_per_cubic)
    if safe_consumption <= minimum_cubic_int:
        return round(minimum_rate_val, 2)
    return round(minimum_rate_val + ((safe_consumption - minimum_cubic_int) * excess_rate_val), 2)


def _calculate_visible_penalty(
    amount_due,
    due_date_value,
    bill_status,
    existing_penalty,
    late_fee,
    reference_date: date,
) -> tuple[float, float]:
    amount_due_val = max(0.0, _safe_float(amount_due))
    stored_penalty = max(0.0, _safe_float(existing_penalty))
    late_fee_percent = _safe_float(late_fee, 10.0) or 10.0
    due_date_obj = _parse_date(due_date_value)
    status_text = str(bill_status or "Unpaid").strip().lower()
    is_overdue = status_text != "paid" and due_date_obj is not None and reference_date > due_date_obj
    if is_overdue:
        computed_penalty = round(amount_due_val * (late_fee_percent / 100.0), 2)
        applied_penalty = max(stored_penalty, computed_penalty)
    else:
        applied_penalty = stored_penalty
    total_after_due_date = round(amount_due_val + applied_penalty, 2)
    return applied_penalty, total_after_due_date


def _build_bill_payload(reading: dict, context: dict, remote_reading_id: int) -> dict:
    reference_date = _reading_date(reading.get("reading_date"))
    present_reading = _safe_int(reading.get("present_reading"))
    consumption = _safe_int(reading.get("consumption"))
    previous_reading = _safe_int(reading.get("previous_reading"), present_reading - consumption)
    current_charge = _compute_charge(
        consumption,
        context.get("minimum_cubic"),
        context.get("minimum_rate"),
        context.get("excess_rate_per_cubic"),
    )

    latest_bill_sync_id = str(context.get("bill_sync_id") or "").strip()
    current_sync_id = str(reading.get("reading_id") or "").strip()
    same_bill = latest_bill_sync_id and current_sync_id and latest_bill_sync_id == current_sync_id

    due_days = _safe_int(context.get("due_days"), 15) or 15
    late_fee_percent = _safe_float(context.get("late_fee"), 10.0) or 10.0
    latest_bill_status = str(context.get("bill_status") or "").strip().lower()
    previous_balance = max(0.0, _safe_float(context.get("previous_balance")))
    latest_amount_due = max(0.0, _safe_float(context.get("amount_due")))
    stored_previous_penalty = max(0.0, _safe_float(context.get("previous_penalty")))
    stored_unpaid_penalty = max(0.0, _safe_float(context.get("penalty")))

    carried_balance = 0.0
    carried_penalty = 0.0
    if same_bill:
        carried_balance = previous_balance
        carried_penalty = stored_previous_penalty
    elif latest_bill_status and latest_bill_status != "paid":
        latest_unpaid_principal = max(0.0, latest_amount_due - stored_previous_penalty)
        carried_balance = max(previous_balance, latest_unpaid_principal)
        computed_previous_penalty = round(carried_balance * (late_fee_percent / 100.0), 2)
        stored_penalty = stored_previous_penalty if previous_balance > 0 else max(stored_previous_penalty, stored_unpaid_penalty)
        carried_penalty = max(stored_penalty, computed_previous_penalty)

    bill_date = datetime.combine(reference_date, datetime.min.time())
    due_date = datetime.combine(reference_date + timedelta(days=due_days), datetime.min.time())
    amount_due = round(current_charge + carried_balance + carried_penalty, 2)
    current_penalty = round(current_charge * (late_fee_percent / 100.0), 2)
    total_amount = amount_due
    total_after_due_date = round(amount_due + current_penalty, 2)
    reading_sync_id = str(reading.get("reading_id") or uuid.uuid4())

    existing_setting_id = context.get("setting_id")
    setting_id = None if existing_setting_id in (None, "") else _safe_int(existing_setting_id)

    return {
        "sync_id": reading_sync_id,
        "consumer_id": _safe_int(reading.get("consumer_id")),
        "reading_id": int(remote_reading_id),
        "billing_officer_id": None,
        "billing_month": bill_date.strftime("%B %Y"),
        "date_covered_from": bill_date.isoformat(sep=" "),
        "date_covered_to": bill_date.isoformat(sep=" "),
        "bill_date": bill_date.isoformat(sep=" "),
        "due_date": due_date.isoformat(sep=" "),
        "disconnection_date": None,
        "class_cost": round(current_charge, 2),
        "water_charge": round(current_charge, 2),
        "meter_maintenance_fee": 0.0,
        "connection_fee": 0.0,
        "amount_due": amount_due,
        "previous_balance": round(carried_balance, 2),
        "previous_penalty": round(carried_penalty, 2),
        "penalty": current_penalty,
        "total_amount": total_amount,
        "total_after_due_date": total_after_due_date,
        "status": "Unpaid",
        "setting_id": setting_id,
        "source_site_id": "meter-reader-device",
        "sync_status": "synced",
        "last_synced_at": datetime.now().replace(tzinfo=None).isoformat(sep=" "),
        "created_by_device": "meter-reader-device",
        "updated_by_device": "meter-reader-device",
        "deleted_at": None,
    }


@dataclass
class SyncConfig:
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    main_pg_host: str
    main_pg_port: int
    main_pg_db: str
    main_pg_user: str
    main_pg_password: str
    supabase_db_schema: str = "public"
    sync_enabled: bool = False

    @classmethod
    def from_env(cls, fail_fast: bool = False) -> "SyncConfig":
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        env_path = os.path.join(project_root, ".env")
        loaded = load_dotenv(env_path)
        if not loaded:
            _load_env_fallback(env_path)

        sync_enabled = os.getenv("HANDHELD_SYNC_ENABLED", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}
        required = [
            "SUPABASE_URL",
            "SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
        ]

        missing = [k for k in required if not os.getenv(k)]
        if (fail_fast or sync_enabled) and missing:
            raise RuntimeError(
                "Missing required sync environment variables: "
                + ", ".join(missing)
                + ". Update .env from .env.example."
            )

        supabase_service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "") or supabase_service_role_key
        return cls(
            supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
            supabase_anon_key=supabase_anon_key,
            supabase_service_role_key=supabase_service_role_key,
            main_pg_host=os.getenv("MAIN_PG_HOST", ""),
            main_pg_port=int(os.getenv("MAIN_PG_PORT", "5432")),
            main_pg_db=os.getenv("MAIN_PG_DB", ""),
            main_pg_user=os.getenv("MAIN_PG_USER", ""),
            main_pg_password=os.getenv("MAIN_PG_PASSWORD", ""),
            supabase_db_schema=os.getenv("SUPABASE_DB_SCHEMA", "public"),
            sync_enabled=sync_enabled,
        )


class LocalSyncStore:
    def ensure_schema(self) -> None:
        raise NotImplementedError

    def cache_reading_schedules(
        self,
        schedules: list[dict],
        meter_reader_id: int | str | None,
        date_from: str | None,
        date_to: str | None,
    ) -> None:
        raise NotImplementedError

    def cache_consumers(self, consumers: list[dict]) -> None:
        raise NotImplementedError

    def load_cached_consumers(self, zone_name: str | None = None) -> list[dict]:
        raise NotImplementedError

    def enqueue_operation(
        self,
        operation: str,
        payload: dict,
        *,
        supabase_status: str = "pending",
        main_pg_status: str = "pending",
    ) -> dict:
        raise NotImplementedError

    def list_pending(self, target: str | None = None) -> list[dict]:
        raise NotImplementedError

    def mark_target_synced(self, queue_id: int, target: str) -> None:
        raise NotImplementedError

    def mark_target_failed(self, queue_id: int, target: str, reason: str) -> None:
        raise NotImplementedError

    def mark_conflict(
        self,
        queue_id: int,
        reason: str,
        server_payload: dict | None = None,
        *,
        target: str | None = None,
    ) -> None:
        raise NotImplementedError

    def log_audit(self, queue_id: int | None, status: str, message: str, payload: dict | None = None) -> None:
        raise NotImplementedError

    def get_recent_audit(self, limit: int = 20) -> list[dict]:
        raise NotImplementedError


class SQLiteLocalSyncStore(LocalSyncStore):
    def __init__(self, cfg: SyncConfig):
        self._has_main_pg = bool(cfg.main_pg_host and cfg.main_pg_db and cfg.main_pg_user)
        self._db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "meter.db"))

    def _connect(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _deserialize_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        for key in ("payload", "server_payload"):
            if key in data and isinstance(data[key], str) and data[key]:
                try:
                    data[key] = json.loads(data[key])
                except Exception:
                    data[key] = {}
            elif key in data and data[key] is None:
                data[key] = {} if key == "server_payload" else data[key]
        return data

    @staticmethod
    def _sqlite_safe(value):
        if isinstance(value, Decimal):
            return float(value)
        return value

    @classmethod
    def _sqlite_safe_row(cls, item: dict) -> dict:
        return {key: cls._sqlite_safe(value) for key, value in item.items()}

    @classmethod
    def _normalize_cached_consumer(cls, item: dict) -> tuple:
        row = cls._sqlite_safe_row(item)
        meter_no = str(row.get("meter_no") or "").strip()
        if not meter_no or meter_no.startswith("ACCT-") or meter_no.startswith("CID-"):
            return ()
        classification_id = row.get("classification_id")
        if classification_id not in (None, ""):
            try:
                classification_id = int(float(classification_id))
            except (TypeError, ValueError):
                classification_id = None
        return (
            _safe_int(row.get("id"), None),
            meter_no,
            row.get("acct_no"),
            row.get("name", ""),
            row.get("address") or row.get("consumer_address") or row.get("service_address"),
            row.get("zone_name"),
            classification_id,
            row.get("classification_name"),
            _safe_int(row.get("minimum_cubic"), None),
            _safe_float(row.get("minimum_rate"), None),
            _safe_float(row.get("excess_rate_per_cubic"), None),
            _safe_int(row.get("due_days"), None),
            _safe_float(row.get("penalty_percent"), None),
            row.get("billing_month"),
            row.get("date_covered_from"),
            row.get("date_covered_to"),
            _safe_float(row.get("amount_due"), None),
            _safe_float(row.get("previous_balance"), None),
            row.get("due_date"),
            _safe_float(row.get("penalty"), None),
            _safe_float(row.get("previous_penalty"), None),
            _safe_float(row.get("total_after_due_date"), None),
            row.get("bill_status"),
            _safe_float(row.get("late_fee"), None),
            _safe_float(row.get("previous_reading"), 0.0),
        )

    def _ensure_columns(self, conn: sqlite3.Connection, table_name: str, column_defs: dict[str, str]) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        for name, definition in column_defs.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")

    @staticmethod
    def _combined_status(supabase_status: str, main_pg_status: str) -> str:
        states = {str(supabase_status or "").lower(), str(main_pg_status or "").lower()}
        if states & {"pending", "failed"}:
            return "failed" if "failed" in states else "pending"
        if "conflict" in states:
            return "conflict"
        return "synced"

    def _refresh_queue_status(self, conn: sqlite3.Connection, queue_id: int) -> None:
        row = conn.execute(
            """
            SELECT supabase_status, main_pg_status, supabase_synced_at, main_pg_synced_at
            FROM sync_queue_meter_readings
            WHERE id = ?
            """,
            (queue_id,),
        ).fetchone()
        if not row:
            return
        status = self._combined_status(row["supabase_status"], row["main_pg_status"])
        synced_at = None
        if status == "synced":
            synced_at = row["main_pg_synced_at"] or row["supabase_synced_at"] or datetime.now().isoformat()
        conn.execute(
            """
            UPDATE sync_queue_meter_readings
            SET status = ?, synced_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, synced_at, queue_id),
        )

    def ensure_schema(self) -> None:
        sql = """
        CREATE TABLE IF NOT EXISTS sync_queue_meter_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,
            operation_id TEXT NOT NULL UNIQUE,
            reading_id TEXT NOT NULL,
            consumer_id INTEGER NOT NULL,
            reading_date TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            supabase_status TEXT NOT NULL DEFAULT 'pending',
            main_pg_status TEXT NOT NULL DEFAULT 'pending',
            retries INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            conflict_reason TEXT,
            server_payload TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            synced_at TEXT,
            supabase_synced_at TEXT,
            main_pg_synced_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_sync_queue_status_created_at
          ON sync_queue_meter_readings (status, created_at);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_sync_queue_stable_key
          ON sync_queue_meter_readings (consumer_id, reading_date, operation_id);

        CREATE TABLE IF NOT EXISTS sync_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_id INTEGER,
            status TEXT NOT NULL,
            message TEXT NOT NULL,
            payload TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS handheld_consumers_cache (
            id INTEGER PRIMARY KEY,
            meter_no TEXT,
            acct_no TEXT,
            name TEXT NOT NULL,
            address TEXT,
            zone_name TEXT,
            classification_id INTEGER,
            classification_name TEXT,
            minimum_cubic INTEGER,
            minimum_rate REAL,
            excess_rate_per_cubic REAL,
            due_days INTEGER,
            penalty_percent REAL,
            billing_month TEXT,
            date_covered_from TEXT,
            date_covered_to TEXT,
            amount_due REAL,
            previous_balance REAL,
            due_date TEXT,
            penalty REAL,
            previous_penalty REAL,
            total_after_due_date REAL,
            bill_status TEXT,
            late_fee REAL,
            previous_reading INTEGER,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reading_schedule (
            schedule_id INTEGER PRIMARY KEY,
            schedule_date TEXT NOT NULL,
            remote_zone_id INTEGER,
            zone_name TEXT NOT NULL,
            meter_reader_id INTEGER,
            meter_reader_name TEXT,
            meter_reader_contact TEXT,
            status TEXT NOT NULL DEFAULT 'Scheduled',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
        with self._connect() as conn:
            conn.executescript(sql)
            self._ensure_columns(
                conn,
                "sync_queue_meter_readings",
                {
                    "supabase_status": "TEXT NOT NULL DEFAULT 'pending'",
                    "main_pg_status": "TEXT NOT NULL DEFAULT 'pending'",
                    "supabase_synced_at": "TEXT",
                    "main_pg_synced_at": "TEXT",
                },
            )
            self._ensure_columns(
                conn,
                "handheld_consumers_cache",
                {
                    "address": "TEXT",
                    "classification_id": "INTEGER",
                    "classification_name": "TEXT",
                    "minimum_cubic": "INTEGER",
                    "minimum_rate": "REAL",
                    "excess_rate_per_cubic": "REAL",
                    "due_days": "INTEGER",
                    "penalty_percent": "REAL",
                    "billing_month": "TEXT",
                    "date_covered_from": "TEXT",
                    "date_covered_to": "TEXT",
                    "amount_due": "REAL",
                    "previous_balance": "REAL",
                    "due_date": "TEXT",
                    "penalty": "REAL",
                    "previous_penalty": "REAL",
                    "total_after_due_date": "REAL",
                    "bill_status": "TEXT",
                    "late_fee": "REAL",
                },
            )
            self._ensure_columns(
                conn,
                "reading_schedule",
                {
                    "schedule_date": "TEXT",
                    "remote_zone_id": "INTEGER",
                    "zone_name": "TEXT",
                    "meter_reader_id": "INTEGER",
                    "meter_reader_name": "TEXT",
                    "meter_reader_contact": "TEXT",
                    "status": "TEXT NOT NULL DEFAULT 'Scheduled'",
                    "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
                },
            )
            conn.commit()

    def cache_reading_schedules(
        self,
        schedules: list[dict],
        meter_reader_id: int | str | None,
        date_from: str | None,
        date_to: str | None,
    ) -> None:
        try:
            reader_id = int(meter_reader_id) if meter_reader_id not in (None, "") else None
        except (TypeError, ValueError):
            reader_id = None
        sql = """
        INSERT INTO reading_schedule (
            schedule_id, schedule_date, remote_zone_id, zone_name, meter_reader_id,
            meter_reader_name, meter_reader_contact, status, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(schedule_id) DO UPDATE SET
            schedule_date = excluded.schedule_date,
            remote_zone_id = excluded.remote_zone_id,
            zone_name = excluded.zone_name,
            meter_reader_id = excluded.meter_reader_id,
            meter_reader_name = excluded.meter_reader_name,
            meter_reader_contact = excluded.meter_reader_contact,
            status = excluded.status,
            updated_at = CURRENT_TIMESTAMP
        """
        with self._connect() as conn:
            if reader_id is not None and date_from and date_to:
                conn.execute(
                    """
                    DELETE FROM reading_schedule
                    WHERE meter_reader_id = ?
                      AND date(schedule_date) >= date(?)
                      AND date(schedule_date) <= date(?)
                    """,
                    (reader_id, date_from, date_to),
                )
            for item in schedules or []:
                if not isinstance(item, dict):
                    continue
                schedule_id = item.get("Schedule_ID", item.get("schedule_id"))
                schedule_date = str(item.get("Schedule_Date", item.get("schedule_date")) or "").split("T", 1)[0].split(" ", 1)[0]
                zone_name = str(item.get("Zone_Name", item.get("zone_name")) or "").strip()
                if not schedule_id or not schedule_date or not zone_name:
                    continue
                try:
                    remote_zone_id = item.get("Zone_ID", item.get("zone_id"))
                    remote_zone_id = int(remote_zone_id) if remote_zone_id not in (None, "") else None
                except (TypeError, ValueError):
                    remote_zone_id = None
                try:
                    schedule_reader_id = item.get("Meter_Reader_ID", item.get("meter_reader_id", reader_id))
                    schedule_reader_id = int(schedule_reader_id) if schedule_reader_id not in (None, "") else reader_id
                except (TypeError, ValueError):
                    schedule_reader_id = reader_id
                conn.execute(
                    sql,
                    (
                        int(schedule_id),
                        schedule_date,
                        remote_zone_id,
                        zone_name,
                        schedule_reader_id,
                        item.get("Meter_Reader_Name", item.get("meter_reader_name")),
                        item.get("Meter_Reader_Contact", item.get("meter_reader_contact")),
                        item.get("Status", item.get("status")) or "Scheduled",
                    ),
                )
            conn.commit()

    def cache_consumers(self, consumers: list[dict]) -> None:
        if not consumers:
            return
        sql = """
        INSERT INTO handheld_consumers_cache (
            id, meter_no, acct_no, name, address, zone_name, classification_id, classification_name,
            minimum_cubic, minimum_rate, excess_rate_per_cubic, due_days, penalty_percent,
            billing_month, date_covered_from, date_covered_to,
            amount_due, previous_balance, due_date, penalty, previous_penalty, total_after_due_date,
            bill_status, late_fee,
            previous_reading, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            meter_no = excluded.meter_no,
            acct_no = excluded.acct_no,
            name = excluded.name,
            address = excluded.address,
            zone_name = excluded.zone_name,
            classification_id = excluded.classification_id,
            classification_name = excluded.classification_name,
            minimum_cubic = excluded.minimum_cubic,
            minimum_rate = excluded.minimum_rate,
            excess_rate_per_cubic = excluded.excess_rate_per_cubic,
            due_days = excluded.due_days,
            penalty_percent = excluded.penalty_percent,
            billing_month = excluded.billing_month,
            date_covered_from = excluded.date_covered_from,
            date_covered_to = excluded.date_covered_to,
            amount_due = excluded.amount_due,
            previous_balance = excluded.previous_balance,
            due_date = excluded.due_date,
            penalty = excluded.penalty,
            previous_penalty = excluded.previous_penalty,
            total_after_due_date = excluded.total_after_due_date,
            bill_status = excluded.bill_status,
            late_fee = excluded.late_fee,
            previous_reading = excluded.previous_reading,
            updated_at = CURRENT_TIMESTAMP
        """
        with self._connect() as conn:
            for item in consumers:
                params = self._normalize_cached_consumer(item)
                if not params:
                    continue
                conn.execute(sql, params)
            conn.commit()

    def load_cached_consumers(self, zone_name: str | None = None) -> list[dict]:
        base = """
        SELECT id, meter_no, acct_no, name, address, zone_name, classification_id, classification_name,
               minimum_cubic, minimum_rate, excess_rate_per_cubic, due_days, penalty_percent,
               billing_month, date_covered_from, date_covered_to,
               amount_due, previous_balance, due_date, penalty, previous_penalty, total_after_due_date,
               bill_status, late_fee,
               previous_reading
        FROM handheld_consumers_cache
        """
        params: tuple = ()
        if zone_name:
            base += " WHERE zone_name = ?"
            params = (zone_name,)
        base += " ORDER BY meter_no"
        with self._connect() as conn:
            rows = conn.execute(base, params).fetchall()
        return [dict(row) for row in rows]

    def enqueue_operation(
        self,
        operation: str,
        payload: dict,
        *,
        supabase_status: str = "pending",
        main_pg_status: str = "pending",
    ) -> dict:
        operation_id = payload.get("operation_id") or str(uuid.uuid4())
        reading_id = payload.get("reading_id") or str(uuid.uuid4())
        payload["operation_id"] = operation_id
        payload["reading_id"] = reading_id
        sql = """
        INSERT INTO sync_queue_meter_readings (
            operation, operation_id, reading_id, consumer_id, reading_date, payload, status, supabase_status, main_pg_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        overall_status = self._combined_status(supabase_status, main_pg_status)
        with self._connect() as conn:
            cur = conn.execute(
                sql,
                (
                    operation,
                    operation_id,
                    reading_id,
                    payload["consumer_id"],
                    payload["reading_date"],
                    json.dumps(payload),
                    overall_status,
                    supabase_status,
                    main_pg_status,
                ),
            )
            row = conn.execute(
                """
                SELECT id, operation_id, reading_id, status, supabase_status, main_pg_status, created_at
                FROM sync_queue_meter_readings
                WHERE id = ?
                """,
                (cur.lastrowid,),
            ).fetchone()
            conn.commit()
        return dict(row) if row else {}

    def list_pending(self, target: str | None = None) -> list[dict]:
        target_column = None
        if target == "supabase":
            target_column = "supabase_status"
        elif target == "main_pg":
            target_column = "main_pg_status"

        sql = """
        SELECT id, operation, operation_id, reading_id, consumer_id, reading_date, payload, status,
               supabase_status, main_pg_status, retries, last_error, created_at
        FROM sync_queue_meter_readings
        """
        if target_column:
            sql += f" WHERE {target_column} IN ('pending', 'failed')"
        else:
            sql += " WHERE supabase_status IN ('pending', 'failed') OR main_pg_status IN ('pending', 'failed')"
        sql += " ORDER BY id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [self._deserialize_row(row) for row in rows]

    def mark_target_synced(self, queue_id: int, target: str) -> None:
        status_column = "main_pg_status" if target == "main_pg" else "supabase_status"
        synced_at_column = "main_pg_synced_at" if target == "main_pg" else "supabase_synced_at"
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE sync_queue_meter_readings
                SET {status_column}='synced', {synced_at_column}=CURRENT_TIMESTAMP, last_error=NULL
                WHERE id = ?
                """,
                (queue_id,),
            )
            self._refresh_queue_status(conn, queue_id)
            conn.commit()

    def mark_target_failed(self, queue_id: int, target: str, reason: str) -> None:
        status_column = "main_pg_status" if target == "main_pg" else "supabase_status"
        scoped_reason = f"{target}: {reason}"[:1000]
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE sync_queue_meter_readings
                SET {status_column}='failed', retries=retries+1, last_error=?
                WHERE id=?
                """,
                (scoped_reason, queue_id),
            )
            self._refresh_queue_status(conn, queue_id)
            conn.commit()

    def mark_conflict(
        self,
        queue_id: int,
        reason: str,
        server_payload: dict | None = None,
        *,
        target: str | None = None,
    ) -> None:
        status_column = "main_pg_status" if target == "main_pg" else "supabase_status"
        scoped_reason = f"{target or 'supabase'}: {reason}"[:1000]
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE sync_queue_meter_readings
                SET {status_column}='conflict', conflict_reason=?, server_payload=?
                WHERE id=?
                """,
                (scoped_reason, json.dumps(server_payload or {}, default=str), queue_id),
            )
            self._refresh_queue_status(conn, queue_id)
            conn.commit()

    def log_audit(self, queue_id: int | None, status: str, message: str, payload: dict | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_audit_log(queue_id, status, message, payload)
                VALUES (?, ?, ?, ?)
                """,
                (queue_id, status, message[:2000], json.dumps(payload or {}, default=str)),
            )
            conn.commit()

    def get_recent_audit(self, limit: int = 20) -> list[dict]:
        sql = """
        SELECT id, queue_id, status, message, payload, created_at
        FROM sync_audit_log
        ORDER BY id DESC
        LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (max(1, min(limit, 200)),)).fetchall()
        return [self._deserialize_row(row) for row in rows]


class SupabaseRestClient:
    _ACCOUNT_CONTACT_SELECTS = (
        "account_id,username,password,role_id,account_status,full_name,contact_number",
        "account_id,username,password,role_id,account_status,full_name,phone_number",
        "account_id,username,password,role_id,account_status,full_name",
    )

    def __init__(self, cfg: SyncConfig):
        self._url = cfg.supabase_url
        self._anon_key = cfg.supabase_anon_key
        self._service_key = cfg.supabase_service_role_key
        self._schema = cfg.supabase_db_schema or "public"
        self._table_columns_cache: dict[str, set[str]] = {}

    def _req(self, method: str, table_or_path: str, *, query: dict | None = None, payload: dict | list | None = None,
             use_service_key: bool = False, extra_headers: dict | None = None) -> tuple[int, object]:
        base = table_or_path if table_or_path.startswith("/") else f"/rest/v1/{table_or_path}"
        url = f"{self._url}{base}"
        if query:
            url += "?" + parse.urlencode(query)
        body = None
        headers = {
            "apikey": self._service_key if use_service_key else self._anon_key,
            "Authorization": f"Bearer {self._service_key if use_service_key else self._anon_key}",
            "Content-Type": "application/json",
            "Accept-Profile": self._schema,
            "Content-Profile": self._schema,
        }
        if extra_headers:
            headers.update(extra_headers)
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=body, method=method, headers=headers)
        try:
            with request.urlopen(req, timeout=6) as resp:
                raw = resp.read().decode("utf-8").strip()
                return resp.getcode(), json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8").strip() if exc.fp else ""
            try:
                return exc.code, json.loads(raw) if raw else {"error": raw or str(exc)}
            except Exception:
                return exc.code, {"error": raw or str(exc)}
        except Exception as exc:
            return 0, {"error": str(exc)}

    def is_online(self) -> bool:
        status, _ = self._req("GET", "/rest/v1/", use_service_key=False)
        return 200 <= status < 500 and status != 0

    def _load_latest_admin_settings(self) -> dict:
        status, data = self._req(
            "GET",
            "admin_settings",
            query={"select": "late_fee", "limit": "1"},
            use_service_key=True,
        )
        if status >= 400 or not isinstance(data, list) or not data:
            return {}
        row = data[0]
        return row if isinstance(row, dict) else {}

    def load_reading_schedules(
        self,
        meter_reader_id: int | str,
        date_from: str,
        date_to: str,
        status: str = "Scheduled",
    ) -> list[dict]:
        query = {
            "meter_reader_id": str(meter_reader_id),
            "date_from": str(date_from),
            "date_to": str(date_to),
            "status": str(status or "Scheduled"),
        }
        http_status, data = self._req("GET", "/api/reading-schedules", query=query, use_service_key=True)
        if http_status >= 400:
            raise RuntimeError(f"Supabase reading schedule lookup failed: {data}")
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def authenticate_meter_reader(self, username: str, password: str) -> dict:
        data = None
        last_error = None
        for select_clause in self._ACCOUNT_CONTACT_SELECTS:
            query = {
                "select": select_clause,
                "username": f"eq.{username}",
                "deleted_at": "is.null",
                "limit": "1",
            }
            status, data = self._req("GET", "accounts", query=query, use_service_key=True)
            if status < 400:
                break
            error_text = json.dumps(data).lower() if isinstance(data, dict) else str(data).lower()
            last_error = data
            if "column" not in error_text or "does not exist" not in error_text:
                raise RuntimeError(f"Supabase account lookup failed: {data}")
        else:
            raise RuntimeError(f"Supabase account lookup failed: {last_error}")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ValueError("Invalid username or password.")
        row = data[0]
        if not _verify_password(password, row.get("password")):
            raise ValueError("Invalid username or password.")
        if int(row.get("role_id") or 0) != 3 or str(row.get("account_status") or "").strip() != "Active":
            raise PermissionError("This account is not an active Meter Reader.")
        contact_number = row.get("contact_number") or row.get("phone_number") or ""
        return {
            "id": row.get("account_id"),
            "account_id": row.get("account_id"),
            "username": row.get("username"),
            "name": row.get("full_name") or row.get("username"),
            "full_name": row.get("full_name") or row.get("username"),
            "contact_number": str(contact_number or "").strip(),
            "role_id": row.get("role_id"),
            "account_status": row.get("account_status"),
            "reader_id": str(row.get("account_id") or ""),
        }

    def _load_latest_billing_settings(self) -> dict:
        status, data = self._req(
            "GET",
            "billing_settings",
            query={"select": "due_days", "order": "setting_id.desc", "limit": "1"},
            use_service_key=True,
        )
        if status >= 400 or not isinstance(data, list) or not data:
            return {}
        row = data[0]
        return row if isinstance(row, dict) else {}

    def _load_waterrates_by_classification(self) -> dict[int, dict]:
        status, data = self._req(
            "GET",
            "waterrates",
            query={
                "select": "classification_id,rate_id,minimum_cubic,minimum_rate,excess_rate_per_cubic",
                "order": "classification_id.asc,rate_id.desc",
            },
            use_service_key=True,
        )
        if status >= 400 or not isinstance(data, list):
            return {}
        rates: dict[int, dict] = {}
        for row in data:
            if not isinstance(row, dict):
                continue
            classification_id = row.get("classification_id")
            if classification_id is None:
                continue
            try:
                key = int(classification_id)
            except (TypeError, ValueError):
                continue
            if key not in rates:
                rates[key] = row
        return rates

    def _batched_consumer_ids(self, consumer_ids: list[int]) -> list[list[int]]:
        normalized = sorted({int(cid) for cid in consumer_ids if cid is not None})
        return [normalized[idx: idx + SYNC_BATCH_SIZE] for idx in range(0, len(normalized), SYNC_BATCH_SIZE)]

    def _fetch_rows_for_consumer_ids(
        self,
        table_name: str,
        select_clause: str,
        consumer_ids: list[int],
        *,
        order_clause: str | None = None,
    ) -> list[dict]:
        rows: list[dict] = []
        for consumer_batch in self._batched_consumer_ids(consumer_ids):
            if not consumer_batch:
                continue
            in_filter = ",".join(str(cid) for cid in consumer_batch)
            query = {
                "select": select_clause,
                "consumer_id": f"in.({in_filter})",
                "limit": str(SYNC_BATCH_SIZE),
            }
            if order_clause:
                query["order"] = order_clause
            status, data = self._req(
                "GET",
                table_name,
                query=query,
                use_service_key=True,
            )
            if status >= 400 or not isinstance(data, list):
                continue
            rows.extend(row for row in data if isinstance(row, dict))
        return rows

    def _bill_select_clause(self) -> str:
        preferred = [
            "bill_id",
            "consumer_id",
            "reading_id",
            "billing_month",
            "date_covered_from",
            "date_covered_to",
            "bill_date",
            "amount_due",
            "due_date",
            "previous_balance",
            "penalty",
            "previous_penalty",
            "total_after_due_date",
            "status",
            "sync_id",
        ]
        allowed = self._get_table_columns("bills")
        if not allowed:
            return ",".join(field for field in preferred if field != "bill_date")
        selected = [field for field in preferred if field in allowed]
        required = {"bill_id", "consumer_id"}
        if not required.issubset(set(selected)):
            return ",".join(field for field in preferred if field != "bill_date")
        return ",".join(selected)

    def _load_latest_bills_by_consumer(self, consumer_ids: list[int]) -> dict[int, dict]:
        if not consumer_ids:
            return {}
        data = self._fetch_rows_for_consumer_ids(
            "bills",
            self._bill_select_clause(),
            consumer_ids,
            order_clause="consumer_id.asc,bill_id.desc",
        )
        bills: dict[int, dict] = {}
        for row in data:
            consumer_id = row.get("consumer_id")
            if consumer_id is None:
                continue
            try:
                key = int(consumer_id)
            except (TypeError, ValueError):
                continue
            normalized_row = dict(row)
            fallback_bill_date = normalized_row.get("bill_date")
            if not normalized_row.get("date_covered_from") and fallback_bill_date not in (None, ""):
                normalized_row["date_covered_from"] = fallback_bill_date
            if not normalized_row.get("date_covered_to") and fallback_bill_date not in (None, ""):
                normalized_row["date_covered_to"] = fallback_bill_date
            selected = bills.get(key)
            row_status = str(normalized_row.get("status") or "").strip().lower()
            selected_status = str((selected or {}).get("status") or "").strip().lower()
            if selected is None:
                bills[key] = normalized_row
            elif selected_status == "paid" and row_status != "paid":
                bills[key] = normalized_row
        return bills

    def _load_latest_meterreadings_by_consumer(self, consumer_ids: list[int]) -> dict[int, dict]:
        if not consumer_ids:
            return {}
        for reading_column in ("current_reading", "present_reading"):
            data = self._fetch_rows_for_consumer_ids(
                "meterreadings",
                f"consumer_id,reading_id,reading_date,updated_at,{reading_column}",
                consumer_ids,
                order_clause="consumer_id.asc,reading_date.desc,updated_at.desc,reading_id.desc",
            )
            latest: dict[int, dict] = {}
            for row in data:
                consumer_id = row.get("consumer_id")
                try:
                    key = int(consumer_id)
                except (TypeError, ValueError):
                    continue
                if key in latest:
                    continue
                value = row.get(reading_column)
                if value is None:
                    continue
                normalized = dict(row)
                normalized["latest_reading"] = value
                latest[key] = normalized
            if latest:
                return latest
        return {}
    def _consumer_select_variants(self, include_reading_fields: bool = True) -> list[str]:
        reading_fields = ",previous_reading,last_reading" if include_reading_fields else ""
        base_suffix = (
            f",first_name,middle_name,last_name,zone_id,classification_id{reading_fields},status,"
            "zone:zone_id(zone_name),classification:classification_id(classification_id,classification_name)"
        )
        return [
            f"consumer_id,account_number,meter_no,address,consumer_address,service_address{base_suffix}",
            f"consumer_id,account_number,meter_number,address,consumer_address,service_address{base_suffix}",
            f"consumer_id,account_number,address,consumer_address,service_address{base_suffix}",
            f"consumer_id,account_number,meter_no,address{base_suffix}",
            f"consumer_id,account_number,meter_number,address{base_suffix}",
            f"consumer_id,account_number,address{base_suffix}",
            f"consumer_id,account_number,meter_no,consumer_address{base_suffix}",
            f"consumer_id,account_number,meter_number,consumer_address{base_suffix}",
            f"consumer_id,account_number,consumer_address{base_suffix}",
            f"consumer_id,account_number,meter_no,service_address{base_suffix}",
            f"consumer_id,account_number,meter_number,service_address{base_suffix}",
            f"consumer_id,account_number,service_address{base_suffix}",
            f"consumer_id,account_number,meter_no{base_suffix}",
            f"consumer_id,account_number,meter_number{base_suffix}",
            f"consumer_id,account_number{base_suffix}",
        ]

    def _fetch_consumer_rows(self, zone_name: str | None = None, consumer_id: int | None = None) -> list[dict]:
        last_error: object = {"error": "No consumer query variant attempted."}
        for include_reading_fields in (True, False):
            for select in self._consumer_select_variants(include_reading_fields=include_reading_fields):
                query = {"select": select}
                if zone_name:
                    query["zone.zone_name"] = f"eq.{zone_name}"
                if consumer_id is not None:
                    query["consumer_id"] = f"eq.{consumer_id}"
                    query["limit"] = "1"
                status, data = self._req("GET", "consumer", query=query, use_service_key=True)
                if status < 400 and isinstance(data, list):
                    return data
                last_error = data
        raise RuntimeError(f"Supabase read failed: {last_error}")

    def _load_meters_by_consumer(self, consumer_ids: list[int]) -> dict[int, dict]:
        if not consumer_ids:
            return {}
        data = self._fetch_rows_for_consumer_ids(
            "meter",
            "meter_id,meter_serial_number,consumer_id",
            consumer_ids,
            order_clause="consumer_id.asc,meter_id.desc",
        )
        meters: dict[int, dict] = {}
        for row in data:
            consumer_id = row.get("consumer_id")
            try:
                key = int(consumer_id)
            except (TypeError, ValueError):
                continue
            if key not in meters:
                meters[key] = row
        return meters

    def load_assigned_consumers(
        self,
        meter_reader_id: int | str | None = None,
        zone_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        zone_filters: list[str] = []
        if meter_reader_id not in (None, ""):
            start_date = date_from or _device_schedule_window()[0]
            end_date = date_to or _device_schedule_window()[1]
            schedules = self.load_reading_schedules(meter_reader_id, start_date, end_date, "Scheduled")
            zone_filters = sorted(
                {
                    str(row.get("Zone_Name") or row.get("zone_name") or "").strip()
                    for row in schedules
                    if str(row.get("Zone_Name") or row.get("zone_name") or "").strip()
                }
            )
            if zone_name:
                zone_filters = [name for name in zone_filters if name == zone_name]
            if not zone_filters:
                return []
            data: list[dict] = []
            seen_consumer_ids: set[int] = set()
            for scheduled_zone in zone_filters:
                zone_rows = self._fetch_consumer_rows(zone_name=scheduled_zone)
                for row in zone_rows:
                    if not isinstance(row, dict):
                        continue
                    cid = row.get("consumer_id") or row.get("id")
                    try:
                        cid_int = int(cid)
                    except (TypeError, ValueError):
                        cid_int = None
                    if cid_int is not None and cid_int in seen_consumer_ids:
                        continue
                    if cid_int is not None:
                        seen_consumer_ids.add(cid_int)
                    data.append(row)
        else:
            data = self._fetch_consumer_rows(zone_name=zone_name)
        if not isinstance(data, list):
            return []
        consumer_ids: list[int] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            cid = row.get("consumer_id") or row.get("id")
            try:
                consumer_ids.append(int(cid))
            except (TypeError, ValueError):
                continue
        admin_settings = self._load_latest_admin_settings()
        billing_settings = self._load_latest_billing_settings()
        rates_by_classification = self._load_waterrates_by_classification()
        bills_by_consumer = self._load_latest_bills_by_consumer(consumer_ids)
        meters_by_consumer = self._load_meters_by_consumer(consumer_ids)
        latest_readings_by_consumer = self._load_latest_meterreadings_by_consumer(consumer_ids)
        normalized: list[dict] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            # Normalize across possible consumer schemas.
            cid = row.get("consumer_id") or row.get("id")
            meter_row = {}
            try:
                meter_row = meters_by_consumer.get(int(cid), {}) if cid is not None else {}
            except (TypeError, ValueError):
                meter_row = {}
            meter_no = row.get("meter_no") or row.get("meter_number") or row.get("meterid") or meter_row.get("meter_serial_number")
            meter_no = str(meter_no or "").strip() or None
            acct_no = row.get("account_number") or row.get("acct_no") or row.get("account_no")
            first = (row.get("first_name") or "").strip()
            middle = (row.get("middle_name") or "").strip()
            last = (row.get("last_name") or "").strip()
            full_from_parts = " ".join([p for p in [first, middle, last] if p]).strip()
            name = row.get("name") or row.get("consumer_name") or row.get("fullname") or full_from_parts
            address = (
                row.get("address")
                or row.get("consumer_address")
                or row.get("service_address")
            )
            zone_obj = row.get("zone")
            if isinstance(zone_obj, dict):
                zone_val = zone_obj.get("zone_name")
            else:
                zone_val = row.get("zone_name") or row.get("zone") or row.get("zone_code")
            classification_id = row.get("classification_id")
            classification_obj = row.get("classification")
            classification_name = None
            if isinstance(classification_obj, dict):
                classification_name = classification_obj.get("classification_name")
            try:
                rate_row = rates_by_classification.get(int(classification_id)) if classification_id is not None else None
            except (TypeError, ValueError):
                rate_row = None
            try:
                bill_row = bills_by_consumer.get(int(cid)) if cid is not None else None
            except (TypeError, ValueError):
                bill_row = None
            latest_reading_row = {}
            try:
                latest_reading_row = latest_readings_by_consumer.get(int(cid), {}) if cid is not None else {}
            except (TypeError, ValueError):
                latest_reading_row = {}
            latest_reading = latest_reading_row.get("latest_reading")
            prev = latest_reading
            if prev is None:
                prev = row.get("previous_reading") if row.get("previous_reading") is not None else row.get("last_reading")
            normalized.append(
                {
                    "id": cid,
                    "meter_no": meter_no,
                    "acct_no": acct_no,
                    "name": name,
                    "address": address,
                    "zone_name": zone_val,
                    "classification_id": classification_id,
                    "classification_name": classification_name,
                    "minimum_cubic": (rate_row or {}).get("minimum_cubic"),
                    "minimum_rate": (rate_row or {}).get("minimum_rate"),
                    "excess_rate_per_cubic": (rate_row or {}).get("excess_rate_per_cubic"),
                    "due_days": billing_settings.get("due_days"),
                    "billing_month": (bill_row or {}).get("billing_month"),
                    "date_covered_from": (bill_row or {}).get("date_covered_from"),
                    "date_covered_to": (bill_row or {}).get("date_covered_to"),
                    "amount_due": (bill_row or {}).get("amount_due"),
                    "previous_balance": (bill_row or {}).get("previous_balance"),
                    "due_date": (bill_row or {}).get("due_date"),
                    "penalty": (bill_row or {}).get("penalty"),
                    "previous_penalty": (bill_row or {}).get("previous_penalty"),
                    "total_after_due_date": (bill_row or {}).get("total_after_due_date"),
                    "bill_status": (bill_row or {}).get("status"),
                    "late_fee": admin_settings.get("late_fee"),
                    "previous_reading": prev if prev is not None else 0,
                    "latest_reading": latest_reading,
                    "latest_reading_id": latest_reading_row.get("reading_id"),
                    "latest_reading_date": latest_reading_row.get("reading_date"),
                    "latest_reading_updated_at": latest_reading_row.get("updated_at"),
                }
            )
        return normalized

    def _get_table_columns(self, table_name: str) -> set[str]:
        cached = self._table_columns_cache.get(table_name)
        if cached is not None:
            return cached
        status, data = self._req("GET", "/rest/v1/", use_service_key=True)
        cols: set[str] = set()
        if status == 200 and isinstance(data, dict):
            path_obj = data.get("paths", {}).get(f"/{table_name}", {})
            # Try to collect insert-able/readable params from OpenAPI shape.
            for method in ("post", "patch", "get"):
                m = path_obj.get(method, {})
                for prm in m.get("parameters", []):
                    schema = prm.get("schema", {})
                    props = schema.get("properties", {})
                    if isinstance(props, dict):
                        cols.update(props.keys())
        # Fallback: probe one row and use keys from response.
        if not cols:
            st2, d2 = self._req("GET", table_name, query={"select": "*", "limit": "1"}, use_service_key=True)
            if st2 < 400 and isinstance(d2, list) and d2 and isinstance(d2[0], dict):
                cols.update(d2[0].keys())
        self._table_columns_cache[table_name] = cols
        return cols

    def find_existing_reading(self, consumer_id: int, reading_date: str) -> dict | None:
        query = {
            "select": "reading_id,consumer_id,reading_date,updated_at,present_reading",
            "consumer_id": f"eq.{consumer_id}",
            "reading_date": f"eq.{reading_date}",
            "order": "updated_at.desc",
            "limit": "1",
        }
        status, data = self._req("GET", "meterreadings", query=query, use_service_key=True)
        if status >= 400:
            return None
        if isinstance(data, list) and data:
            return data[0]
        return None

    def get_consumer_context(self, consumer_id: int) -> dict:
        data = self._fetch_consumer_rows(consumer_id=consumer_id)
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return {}
        consumer_row = data[0]
        classification_id = consumer_row.get("classification_id")
        rates_by_classification = self._load_waterrates_by_classification()
        admin_settings = self._load_latest_admin_settings()
        billing_settings = self._load_latest_billing_settings()
        bills_by_consumer = self._load_latest_bills_by_consumer([int(consumer_id)])
        meter_status, meter_data = self._req(
            "GET",
            "meter",
            query={"select": "meter_id,meter_serial_number,consumer_id", "consumer_id": f"eq.{consumer_id}", "limit": "1"},
            use_service_key=True,
        )
        meter_row = meter_data[0] if meter_status < 400 and isinstance(meter_data, list) and meter_data and isinstance(meter_data[0], dict) else {}
        latest_bill = bills_by_consumer.get(int(consumer_id), {})
        try:
            rate_row = rates_by_classification.get(int(classification_id)) if classification_id is not None else {}
        except (TypeError, ValueError):
            rate_row = {}
        zone_obj = consumer_row.get("zone")
        classification_obj = consumer_row.get("classification")
        latest_reading = self._load_latest_meterreadings_by_consumer([int(consumer_id)]).get(int(consumer_id), {}).get("latest_reading")
        return {
            "consumer_id": consumer_id,
            "acct_no": consumer_row.get("account_number"),
            "meter_no": (str(consumer_row.get("meter_no") or consumer_row.get("meter_number") or meter_row.get("meter_serial_number") or "").strip() or None),
            "address": consumer_row.get("address") or consumer_row.get("consumer_address") or consumer_row.get("service_address"),
            "zone_name": zone_obj.get("zone_name") if isinstance(zone_obj, dict) else None,
            "classification_id": classification_id,
            "classification_name": classification_obj.get("classification_name") if isinstance(classification_obj, dict) else None,
            "minimum_cubic": rate_row.get("minimum_cubic"),
            "minimum_rate": rate_row.get("minimum_rate"),
            "excess_rate_per_cubic": rate_row.get("excess_rate_per_cubic"),
            "due_days": billing_settings.get("due_days"),
            "late_fee": admin_settings.get("late_fee"),
            "previous_reading": latest_reading if latest_reading is not None else (consumer_row.get("previous_reading") if consumer_row.get("previous_reading") is not None else consumer_row.get("last_reading")),
            "billing_month": latest_bill.get("billing_month"),
            "date_covered_from": latest_bill.get("date_covered_from"),
            "date_covered_to": latest_bill.get("date_covered_to"),
            "amount_due": latest_bill.get("amount_due"),
            "due_date": latest_bill.get("due_date"),
            "penalty": latest_bill.get("penalty"),
            "previous_penalty": latest_bill.get("previous_penalty"),
            "previous_balance": latest_bill.get("previous_balance"),
            "total_after_due_date": latest_bill.get("total_after_due_date"),
            "bill_status": latest_bill.get("status"),
            "bill_sync_id": latest_bill.get("sync_id"),
            "bill_reading_id": latest_bill.get("reading_id"),
            "meter_id": meter_row.get("meter_id"),
        }

    def _build_remote_payload(self, payload: dict) -> dict:
        rid = payload.get("reading_id")
        rid_int = None
        try:
            if rid is not None and str(rid).isdigit():
                rid_int = int(str(rid))
        except Exception:
            rid_int = None

        candidate_payload = {
            # Send reading_id only if numeric and compatible with remote integer column.
            "reading_id": rid_int,
            "consumer_id": payload.get("consumer_id"),
            # Remote schema uses current_reading instead of present_reading.
            "sync_id": payload.get("reading_id"),
            "current_reading": payload.get("present_reading"),
            "previous_reading": payload.get("previous_reading"),
            "consumption": payload.get("consumption"),
            "excess_consumption": max(0, _safe_int(payload.get("consumption")) - _safe_int(payload.get("minimum_cubic"))),
            # Remote schema uses notes instead of exception.
            "notes": payload.get("exception"),
            "reading_date": _parse_datetime(payload.get("reading_date")).isoformat(sep=" ") if _parse_datetime(payload.get("reading_date")) else None,
            "source_site_id": "meter-reader-device",
            "sync_status": "synced",
            "last_synced_at": datetime.now().replace(tzinfo=None).isoformat(sep=" "),
            "created_by_device": "meter-reader-device",
            "updated_by_device": "meter-reader-device",
        }

        consumer_id = payload.get("consumer_id")
        ctx = self.get_consumer_context(int(consumer_id)) if consumer_id is not None else {}
        if ctx:
            candidate_payload.setdefault("route_id", ctx.get("route_id"))
            candidate_payload.setdefault("meter_id", ctx.get("meter_id"))
            candidate_payload.setdefault("meter_reader_id", ctx.get("meter_reader_id"))

        candidate_payload = {k: v for k, v in candidate_payload.items() if v is not None}
        allowed = self._get_table_columns("meterreadings")
        remote_payload = {k: v for k, v in candidate_payload.items() if (not allowed or k in allowed)}
        if not remote_payload:
            raise RuntimeError("No compatible columns found for meterreadings payload.")

        # Preflight only core fields that should always exist for a reading row.
        required_if_available = ("consumer_id", "reading_date")
        missing_required = [k for k in required_if_available if ((not allowed or k in allowed) and k not in remote_payload)]
        if missing_required:
            raise ValueError(
                f"Missing required fields for remote meterreadings row: {', '.join(missing_required)}. "
                "Consumer mapping may be missing."
            )

        return remote_payload

    def upsert_meter_reading(self, payload: dict) -> dict:
        remote_payload = self._build_remote_payload(payload)

        headers = {
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        query = {"on_conflict": "sync_id"} if remote_payload.get("sync_id") else {}

        status, data = self._req(
            "POST",
            "meterreadings",
            payload=remote_payload,
            use_service_key=True,
            extra_headers=headers,
            query=query if query else None,
        )
        if status >= 400:
            raise RuntimeError(f"Supabase write failed: {data}")
        if isinstance(data, list) and data:
            return data[0]
        return remote_payload

    def upsert_bill(self, payload: dict) -> dict:
        allowed = self._get_table_columns("bills")
        remote_payload = {k: v for k, v in payload.items() if (not allowed or k in allowed)}
        headers = {"Prefer": "resolution=merge-duplicates,return=representation"}
        status, data = self._req(
            "POST",
            "bills",
            payload=remote_payload,
            use_service_key=True,
            extra_headers=headers,
            query={"on_conflict": "sync_id"},
        )
        if status >= 400:
            raise RuntimeError(f"Supabase bill write failed: {data}")
        if isinstance(data, list) and data:
            return data[0]
        return remote_payload

    def save_reading_bundle(self, payload: dict) -> dict:
        context = self.get_consumer_context(int(payload["consumer_id"]))
        merged = dict(context)
        merged.update(payload)
        remote_reading = self.upsert_meter_reading(merged)
        remote_reading_id = remote_reading.get("reading_id")
        if remote_reading_id is None:
            raise RuntimeError("Supabase did not return a reading_id for billing sync.")
        bill_payload = _build_bill_payload(merged, context, int(remote_reading_id))
        remote_bill = self.upsert_bill(bill_payload)
        return {"meterreading": remote_reading, "bill": remote_bill}


class MainPostgresClient:
    """Direct pull from main PostgreSQL as fallback when Supabase is unreachable."""

    def __init__(self, cfg: SyncConfig):
        import psycopg2
        from psycopg2.extras import RealDictCursor
        self._psycopg2 = psycopg2
        self._dict_cursor = RealDictCursor
        self._cfg = cfg
        self._schema = cfg.supabase_db_schema or "public"

    def _connect(self):
        return self._psycopg2.connect(
            host=self._cfg.main_pg_host,
            port=self._cfg.main_pg_port,
            dbname=self._cfg.main_pg_db,
            user=self._cfg.main_pg_user,
            password=self._cfg.main_pg_password,
            connect_timeout=5,
        )

    def is_online(self) -> bool:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return True
        except Exception:
            return False

    def load_waterrates_by_classification(self) -> dict[int, dict]:
        sql = f"""
        SELECT DISTINCT ON (wr.classification_id)
            wr.classification_id,
            wr.rate_id,
            wr.minimum_cubic,
            wr.minimum_rate,
            wr.excess_rate_per_cubic
        FROM {self._schema}.waterrates wr
        WHERE wr.classification_id IS NOT NULL
        ORDER BY wr.classification_id, wr.rate_id DESC
        """
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._dict_cursor) as cur:
                cur.execute(sql)
                rows = cur.fetchall()
        rates: dict[int, dict] = {}
        for row in rows:
            classification_id = row.get("classification_id") if isinstance(row, dict) else None
            if classification_id is None:
                continue
            try:
                rates[int(classification_id)] = dict(row)
            except (TypeError, ValueError):
                continue
        return rates

    def authenticate_meter_reader(self, username: str, password: str) -> dict:
        select_variants = (
            """
            SELECT
                account_id,
                username,
                password,
                role_id,
                account_status,
                full_name,
                contact_number
            FROM {schema}.accounts
            WHERE username = %s
              AND deleted_at IS NULL
            LIMIT 1
            """,
            """
            SELECT
                account_id,
                username,
                password,
                role_id,
                account_status,
                full_name,
                phone_number
            FROM {schema}.accounts
            WHERE username = %s
              AND deleted_at IS NULL
            LIMIT 1
            """,
            """
            SELECT
                account_id,
                username,
                password,
                role_id,
                account_status,
                full_name
            FROM {schema}.accounts
            WHERE username = %s
              AND deleted_at IS NULL
            LIMIT 1
            """,
        )
        row = None
        last_error = None
        for sql_template in select_variants:
            sql = sql_template.format(schema=self._schema)
            try:
                with self._connect() as conn:
                    with conn.cursor(cursor_factory=self._dict_cursor) as cur:
                        cur.execute(sql, (username,))
                        row = cur.fetchone()
                break
            except Exception as exc:
                error_text = str(exc).lower()
                last_error = exc
                if "column" not in error_text or "does not exist" not in error_text:
                    raise
        else:
            if last_error is not None:
                raise last_error
        if not row:
            raise ValueError("Invalid username or password.")
        record = dict(row)
        if not _verify_password(password, record.get("password")):
            raise ValueError("Invalid username or password.")
        if int(record.get("role_id") or 0) != 3 or str(record.get("account_status") or "").strip() != "Active":
            raise PermissionError("This account is not an active Meter Reader.")
        contact_number = record.get("contact_number") or record.get("phone_number") or ""
        return {
            "id": record.get("account_id"),
            "account_id": record.get("account_id"),
            "username": record.get("username"),
            "name": record.get("full_name") or record.get("username"),
            "full_name": record.get("full_name") or record.get("username"),
            "contact_number": str(contact_number or "").strip(),
            "role_id": record.get("role_id"),
            "account_status": record.get("account_status"),
            "reader_id": str(record.get("account_id") or ""),
        }

    def load_reading_schedules(
        self,
        meter_reader_id: int | str,
        date_from: str,
        date_to: str,
        status: str = "Scheduled",
    ) -> list[dict]:
        query_variants = (
            """
            SELECT
                rs.schedule_id AS "Schedule_ID",
                rs.schedule_date::date AS "Schedule_Date",
                rs.zone_id AS "Zone_ID",
                z.zone_name AS "Zone_Name",
                rs.meter_reader_id AS "Meter_Reader_ID",
                COALESCE(a.full_name, a.username) AS "Meter_Reader_Name",
                COALESCE(a.contact_number, '') AS "Meter_Reader_Contact",
                rs.status AS "Status"
            FROM {schema}.reading_schedule rs
            JOIN {schema}.zone z ON z.zone_id = rs.zone_id
            LEFT JOIN {schema}.accounts a ON a.account_id = rs.meter_reader_id
            WHERE rs.meter_reader_id = %s
              AND rs.schedule_date::date >= %s
              AND rs.schedule_date::date <= %s
              AND rs.status = %s
            ORDER BY rs.schedule_date ASC, rs.schedule_id ASC
            """,
            """
            SELECT
                rs.schedule_id AS "Schedule_ID",
                rs.schedule_date::date AS "Schedule_Date",
                rs.zone_id AS "Zone_ID",
                z.zone_name AS "Zone_Name",
                rs.meter_reader_id AS "Meter_Reader_ID",
                COALESCE(a.full_name, a.username) AS "Meter_Reader_Name",
                COALESCE(a.phone_number, '') AS "Meter_Reader_Contact",
                rs.status AS "Status"
            FROM {schema}.reading_schedule rs
            JOIN {schema}.zone z ON z.zone_id = rs.zone_id
            LEFT JOIN {schema}.accounts a ON a.account_id = rs.meter_reader_id
            WHERE rs.meter_reader_id = %s
              AND rs.schedule_date::date >= %s
              AND rs.schedule_date::date <= %s
              AND rs.status = %s
            ORDER BY rs.schedule_date ASC, rs.schedule_id ASC
            """,
            """
            SELECT
                rs.schedule_id AS "Schedule_ID",
                rs.schedule_date::date AS "Schedule_Date",
                rs.zone_id AS "Zone_ID",
                z.zone_name AS "Zone_Name",
                rs.meter_reader_id AS "Meter_Reader_ID",
                COALESCE(a.full_name, a.username) AS "Meter_Reader_Name",
                '' AS "Meter_Reader_Contact",
                rs.status AS "Status"
            FROM {schema}.reading_schedule rs
            JOIN {schema}.zone z ON z.zone_id = rs.zone_id
            LEFT JOIN {schema}.accounts a ON a.account_id = rs.meter_reader_id
            WHERE rs.meter_reader_id = %s
              AND rs.schedule_date::date >= %s
              AND rs.schedule_date::date <= %s
              AND rs.status = %s
            ORDER BY rs.schedule_date ASC, rs.schedule_id ASC
            """,
        )
        rows = []
        last_error = None
        for sql_template in query_variants:
            sql = sql_template.format(schema=self._schema)
            try:
                with self._connect() as conn:
                    with conn.cursor(cursor_factory=self._dict_cursor) as cur:
                        cur.execute(sql, (int(meter_reader_id), date_from, date_to, status or "Scheduled"))
                        rows = cur.fetchall()
                break
            except Exception as exc:
                error_text = str(exc).lower()
                last_error = exc
                if "column" not in error_text or "does not exist" not in error_text:
                    raise
        else:
            if last_error is not None:
                raise last_error
        return [dict(r) for r in rows]

    def _load_active_consumers_for_zone(self, zone_name: str) -> list[dict]:
        sql = f"""
        SELECT
            c.consumer_id AS id,
            COALESCE(NULLIF(c.meter_number, ''), NULLIF(m.meter_serial_number, '')) AS meter_no,
            c.account_number AS acct_no,
            CONCAT_WS(' ', c.first_name, c.middle_name, c.last_name) AS name,
            z.zone_name AS zone_name,
            c.classification_id,
            cls.classification_name,
            wr.minimum_cubic,
            wr.minimum_rate,
            wr.excess_rate_per_cubic,
            bs.due_days,
            lb.billing_month,
            lb.date_covered_from,
            lb.date_covered_to,
            lb.amount_due,
            lb.due_date,
            lb.penalty,
            lb.previous_penalty,
            lb.total_after_due_date,
            lb.status AS bill_status,
            adm.late_fee,
            COALESCE(prev.last_reading, 0)::int AS previous_reading
        FROM {self._schema}.consumer c
        JOIN {self._schema}.zone z ON z.zone_id = c.zone_id
        LEFT JOIN {self._schema}.classification cls ON cls.classification_id = c.classification_id
        LEFT JOIN LATERAL (
            SELECT minimum_cubic, minimum_rate, excess_rate_per_cubic
            FROM {self._schema}.waterrates wr
            WHERE wr.classification_id = c.classification_id
            ORDER BY wr.rate_id DESC
            LIMIT 1
        ) wr ON TRUE
        LEFT JOIN (
            SELECT due_days
            FROM {self._schema}.billing_settings
            ORDER BY setting_id DESC
            LIMIT 1
        ) bs ON TRUE
        LEFT JOIN (
            SELECT late_fee
            FROM {self._schema}.admin_settings
            LIMIT 1
        ) adm ON TRUE
        LEFT JOIN LATERAL (
            SELECT billing_month, date_covered_from, date_covered_to,
                   amount_due, due_date, penalty, previous_penalty, total_after_due_date, status
            FROM {self._schema}.bills b
            WHERE b.consumer_id = c.consumer_id
            ORDER BY b.bill_id DESC
            LIMIT 1
        ) lb ON TRUE
        LEFT JOIN {self._schema}.meter m ON m.consumer_id = c.consumer_id
        LEFT JOIN LATERAL (
            SELECT mr.current_reading AS last_reading
            FROM {self._schema}.meterreadings mr
            WHERE mr.consumer_id = c.consumer_id
            ORDER BY mr.reading_date DESC NULLS LAST, mr.updated_at DESC NULLS LAST, mr.reading_id DESC
            LIMIT 1
        ) prev ON TRUE
        WHERE c.status = 'Active'
          AND z.zone_name = %s
        ORDER BY c.consumer_id
        """
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._dict_cursor) as cur:
                cur.execute(sql, (zone_name,))
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def load_assigned_consumers(
        self,
        meter_reader_id: int | str | None = None,
        zone_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        if meter_reader_id in (None, ""):
            zone_filters = [zone_name] if zone_name else []
        else:
            schedules = self.load_reading_schedules(
                meter_reader_id,
                date_from or _device_schedule_window()[0],
                date_to or _device_schedule_window()[1],
                "Scheduled",
            )
            zone_filters = sorted(
                {
                    str(row.get("Zone_Name") or "").strip()
                    for row in schedules
                    if str(row.get("Zone_Name") or "").strip()
                }
            )
            if zone_name:
                zone_filters = [name for name in zone_filters if name == zone_name]
        if not zone_filters:
            return []
        rows: list[dict] = []
        seen: set[int] = set()
        for scheduled_zone in zone_filters:
            for row in self._load_active_consumers_for_zone(scheduled_zone):
                cid = row.get("id")
                try:
                    cid_int = int(cid)
                except (TypeError, ValueError):
                    cid_int = None
                if cid_int is not None and cid_int in seen:
                    continue
                if cid_int is not None:
                    seen.add(cid_int)
                rows.append(row)
        return rows

    def get_consumer_context(self, consumer_id: int) -> dict:
        sql = f"""
        SELECT
            c.consumer_id,
            c.account_number AS acct_no,
            COALESCE(NULLIF(c.meter_number, ''), NULLIF(m.meter_serial_number, '')) AS meter_no,
            z.zone_name,
            c.classification_id,
            cls.classification_name,
            wr.minimum_cubic,
            wr.minimum_rate,
            wr.excess_rate_per_cubic,
            bs.setting_id,
            bs.due_days,
            adm.late_fee,
            m.meter_id,
            COALESCE(prev.last_reading, 0)::int AS previous_reading,
            lb.billing_month,
            lb.date_covered_from,
            lb.date_covered_to,
            lb.amount_due,
            lb.due_date,
            lb.previous_balance,
            lb.penalty,
            lb.previous_penalty,
            lb.total_after_due_date,
            lb.status AS bill_status,
            lb.sync_id AS bill_sync_id,
            lb.reading_id AS bill_reading_id
        FROM {self._schema}.consumer c
        JOIN {self._schema}.zone z ON z.zone_id = c.zone_id
        LEFT JOIN {self._schema}.classification cls ON cls.classification_id = c.classification_id
        LEFT JOIN LATERAL (
            SELECT minimum_cubic, minimum_rate, excess_rate_per_cubic
            FROM {self._schema}.waterrates wr
            WHERE wr.classification_id = c.classification_id
            ORDER BY wr.rate_id DESC
            LIMIT 1
        ) wr ON TRUE
        LEFT JOIN (
            SELECT setting_id, due_days
            FROM {self._schema}.billing_settings
            ORDER BY setting_id DESC
            LIMIT 1
        ) bs ON TRUE
        LEFT JOIN (
            SELECT late_fee
            FROM {self._schema}.admin_settings
            ORDER BY settings_id DESC
            LIMIT 1
        ) adm ON TRUE
        LEFT JOIN LATERAL (
            SELECT billing_month, date_covered_from, date_covered_to,
                   amount_due, due_date, previous_balance, penalty, previous_penalty, total_after_due_date, status, sync_id, reading_id
            FROM {self._schema}.bills b
            WHERE b.consumer_id = c.consumer_id
            ORDER BY b.bill_id DESC
            LIMIT 1
        ) lb ON TRUE
        LEFT JOIN {self._schema}.meter m ON m.consumer_id = c.consumer_id
        LEFT JOIN LATERAL (
            SELECT mr.current_reading AS last_reading
            FROM {self._schema}.meterreadings mr
            WHERE mr.consumer_id = c.consumer_id
            ORDER BY mr.reading_date DESC NULLS LAST, mr.updated_at DESC NULLS LAST, mr.reading_id DESC
            LIMIT 1
        ) prev ON TRUE
        WHERE c.consumer_id = %s
        LIMIT 1
        """
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._dict_cursor) as cur:
                cur.execute(sql, (consumer_id,))
                row = cur.fetchone()
        return dict(row) if row else {}

    def find_existing_reading(self, consumer_id: int, reading_date: str) -> dict | None:
        reading_dt = _parse_datetime(reading_date)
        if reading_dt is None:
            return None
        sql = f"""
        SELECT reading_id, consumer_id, reading_date, updated_at, current_reading AS present_reading, sync_id
        FROM {self._schema}.meterreadings
        WHERE consumer_id = %s
          AND DATE(reading_date) = %s
          AND deleted_at IS NULL
        ORDER BY updated_at DESC, reading_id DESC
        LIMIT 1
        """
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._dict_cursor) as cur:
                cur.execute(sql, (consumer_id, reading_dt.date()))
                row = cur.fetchone()
        return dict(row) if row else None

    def upsert_meter_reading(self, payload: dict) -> dict:
        context = self.get_consumer_context(int(payload["consumer_id"]))
        merged = dict(context)
        merged.update(payload)
        reading_dt = _parse_datetime(merged.get("reading_date")) or datetime.now().replace(tzinfo=None)
        previous_reading = _safe_int(merged.get("previous_reading"), _safe_int(merged.get("present_reading")) - _safe_int(merged.get("consumption")))
        sql = f"""
        INSERT INTO {self._schema}.meterreadings (
            route_id, consumer_id, meter_id, meter_reader_id, created_date, reading_status,
            previous_reading, current_reading, consumption, excess_consumption, notes,
            status, reading_date, sync_id, created_at, updated_at, source_site_id,
            sync_status, last_synced_at, created_by_device, updated_by_device, deleted_at
        ) VALUES (
            %s, %s, %s, %s, CURRENT_TIMESTAMP, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s,
            %s, CURRENT_TIMESTAMP, %s, %s, NULL
        )
        ON CONFLICT (sync_id) DO UPDATE SET
            route_id = EXCLUDED.route_id,
            meter_id = EXCLUDED.meter_id,
            meter_reader_id = EXCLUDED.meter_reader_id,
            previous_reading = EXCLUDED.previous_reading,
            current_reading = EXCLUDED.current_reading,
            consumption = EXCLUDED.consumption,
            excess_consumption = EXCLUDED.excess_consumption,
            notes = EXCLUDED.notes,
            reading_status = EXCLUDED.reading_status,
            status = EXCLUDED.status,
            reading_date = EXCLUDED.reading_date,
            source_site_id = EXCLUDED.source_site_id,
            sync_status = EXCLUDED.sync_status,
            last_synced_at = EXCLUDED.last_synced_at,
            updated_by_device = EXCLUDED.updated_by_device
        RETURNING *
        """
        params = (
            merged.get("route_id"),
            int(merged["consumer_id"]),
            merged.get("meter_id"),
            merged.get("meter_reader_id"),
            "Flagged" if merged.get("is_flagged") else "Pending",
            previous_reading,
            _safe_float(merged.get("present_reading")),
            _safe_float(merged.get("consumption")),
            max(0, _safe_float(merged.get("consumption")) - _safe_float(merged.get("minimum_cubic"))),
            merged.get("exception"),
            "Active",
            reading_dt,
            str(merged.get("reading_id") or uuid.uuid4()),
            "meter-reader-device",
            "synced",
            "meter-reader-device",
            "meter-reader-device",
        )
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._dict_cursor) as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                conn.commit()
        return dict(row) if row else {}

    def upsert_bill(self, payload: dict) -> dict:
        sql = f"""
        INSERT INTO {self._schema}.bills (
            consumer_id, reading_id, billing_officer_id, billing_month, date_covered_from,
            date_covered_to, bill_date, due_date, disconnection_date, class_cost, water_charge,
            meter_maintenance_fee, connection_fee, amount_due, previous_balance, previous_penalty,
            penalty, total_amount, total_after_due_date, status, setting_id, sync_id,
            created_at, updated_at, source_site_id, sync_status, last_synced_at,
            created_by_device, updated_by_device, deleted_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s, %s, %s,
            %s, %s, NULL
        )
        ON CONFLICT (sync_id) DO UPDATE SET
            consumer_id = EXCLUDED.consumer_id,
            reading_id = EXCLUDED.reading_id,
            billing_officer_id = EXCLUDED.billing_officer_id,
            billing_month = EXCLUDED.billing_month,
            date_covered_from = EXCLUDED.date_covered_from,
            date_covered_to = EXCLUDED.date_covered_to,
            bill_date = EXCLUDED.bill_date,
            due_date = EXCLUDED.due_date,
            disconnection_date = EXCLUDED.disconnection_date,
            class_cost = EXCLUDED.class_cost,
            water_charge = EXCLUDED.water_charge,
            meter_maintenance_fee = EXCLUDED.meter_maintenance_fee,
            connection_fee = EXCLUDED.connection_fee,
            amount_due = EXCLUDED.amount_due,
            previous_balance = EXCLUDED.previous_balance,
            previous_penalty = EXCLUDED.previous_penalty,
            penalty = EXCLUDED.penalty,
            total_amount = EXCLUDED.total_amount,
            total_after_due_date = EXCLUDED.total_after_due_date,
            status = EXCLUDED.status,
            setting_id = EXCLUDED.setting_id,
            source_site_id = EXCLUDED.source_site_id,
            sync_status = EXCLUDED.sync_status,
            last_synced_at = EXCLUDED.last_synced_at,
            updated_by_device = EXCLUDED.updated_by_device
        RETURNING *
        """
        params = (
            payload.get("consumer_id"),
            payload.get("reading_id"),
            payload.get("billing_officer_id"),
            _safe_int(payload.get("billing_month"), 0) if False else payload.get("billing_month"),
            _parse_datetime(payload.get("date_covered_from")),
            _parse_datetime(payload.get("date_covered_to")),
            _parse_datetime(payload.get("bill_date")),
            _parse_datetime(payload.get("due_date")),
            _parse_datetime(payload.get("disconnection_date")),
            _safe_float(payload.get("class_cost")),
            _safe_float(payload.get("water_charge")),
            _safe_float(payload.get("meter_maintenance_fee")),
            _safe_float(payload.get("connection_fee")),
            _safe_float(payload.get("amount_due")),
            _safe_float(payload.get("previous_balance")),
            _safe_float(payload.get("previous_penalty")),
            _safe_float(payload.get("penalty")),
            _safe_float(payload.get("total_amount")),
            _safe_float(payload.get("total_after_due_date")),
            payload.get("status") or "Unpaid",
            payload.get("setting_id"),
            payload.get("sync_id"),
            payload.get("source_site_id") or "meter-reader-device",
            payload.get("sync_status") or "synced",
            _parse_datetime(payload.get("last_synced_at")) or datetime.now().replace(tzinfo=None),
            payload.get("created_by_device") or "meter-reader-device",
            payload.get("updated_by_device") or "meter-reader-device",
        )
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._dict_cursor) as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                conn.commit()
        return dict(row) if row else {}

    def save_reading_bundle(self, payload: dict) -> dict:
        context = self.get_consumer_context(int(payload["consumer_id"]))
        merged = dict(context)
        merged.update(payload)
        reading_row = self.upsert_meter_reading(merged)
        reading_id = reading_row.get("reading_id")
        if reading_id is None:
            raise RuntimeError("MAIN_PG did not return a reading_id for billing sync.")
        bill_payload = _build_bill_payload(merged, context, int(reading_id))
        bill_row = self.upsert_bill(bill_payload)
        return {"meterreading": reading_row, "bill": bill_row}


class HandheldSyncDataAccess:
    """
    Required handheld DAL methods:
    - loadAssignedConsumers
    - saveMeterReading
    - updateMeterReading
    - listPendingSyncReadings
    - syncPendingReadings
    """

    def __init__(self, local_store: LocalSyncStore, remote_store: SupabaseRestClient, main_pg_client=None):
        self.local = local_store
        self.remote = remote_store
        self.main_pg = main_pg_client
        self._worker_stop = threading.Event()
        self._worker: threading.Thread | None = None
        self.local.ensure_schema()

    @classmethod
    def from_env(cls, fail_fast: bool = False) -> "HandheldSyncDataAccess":
        cfg = SyncConfig.from_env(fail_fast=fail_fast)
        main_pg_client = None
        try:
            if cfg.main_pg_host and cfg.main_pg_db and cfg.main_pg_user:
                main_pg_client = MainPostgresClient(cfg)
        except Exception:
            main_pg_client = None
        return cls(SQLiteLocalSyncStore(cfg), SupabaseRestClient(cfg), main_pg_client=main_pg_client)

    def is_online(self) -> bool:
        return bool(self.remote and self.remote.is_online())

    def _main_pg_online(self) -> bool:
        return bool(self.main_pg and self.main_pg.is_online())

    def _available_targets(self, *, include_supabase: bool = True, include_main_pg: bool = False) -> list[tuple[str, str, object]]:
        targets: list[tuple[str, str, object]] = []
        if include_supabase and self.remote and self.remote.is_online():
            targets.append(("Supabase", "supabase", self.remote))
        if include_main_pg and self.main_pg and self.main_pg.is_online():
            targets.append(("MAIN_PG", "main_pg", self.main_pg))
        return targets

    def _sync_reading_to_targets(
        self,
        reading: dict,
        *,
        include_supabase: bool = True,
        include_main_pg: bool = False,
    ) -> tuple[dict[str, dict], list[str]]:
        results: dict[str, dict] = {}
        errors: list[str] = []
        for label, _target_key, target in self._available_targets(
            include_supabase=include_supabase,
            include_main_pg=include_main_pg,
        ):
            try:
                bundle_writer = getattr(target, "save_reading_bundle", None)
                if callable(bundle_writer):
                    results[label] = bundle_writer(reading)
                else:
                    results[label] = {"meterreading": target.upsert_meter_reading(reading)}
            except Exception as exc:
                errors.append(f"{label}: {exc}")
        return results, errors

    def _overlay_main_pg_rates_for_consumers(self, consumers: list[dict]) -> list[dict]:
        if not consumers or not self.main_pg:
            return consumers
        try:
            rates_by_classification = self.main_pg.load_waterrates_by_classification()
        except Exception:
            return consumers

        overlaid: list[dict] = []
        for item in consumers:
            row = dict(item)
            classification_id = row.get("classification_id")
            try:
                rate_row = rates_by_classification.get(int(classification_id)) if classification_id is not None else None
            except (TypeError, ValueError):
                rate_row = None
            if rate_row:
                row["minimum_cubic"] = rate_row.get("minimum_cubic")
                row["minimum_rate"] = rate_row.get("minimum_rate")
                row["excess_rate_per_cubic"] = rate_row.get("excess_rate_per_cubic")
            overlaid.append(row)
        return overlaid

    def _overlay_main_pg_rates_for_reading(self, reading: dict) -> dict:
        if not self.main_pg:
            return reading
        consumer_id = reading.get("consumer_id")
        if consumer_id in (None, ""):
            return reading
        try:
            context = self.main_pg.get_consumer_context(int(consumer_id))
        except Exception:
            return reading
        merged = dict(reading)
        for field_name in ("minimum_cubic", "minimum_rate", "excess_rate_per_cubic"):
            value = context.get(field_name)
            if value is not None and value != "":
                merged[field_name] = value
        return merged

    def _find_existing_reading_with_fallback(
        self,
        payload: dict,
        *,
        include_supabase: bool = True,
        include_main_pg: bool = False,
    ) -> tuple[dict | None, list[str]]:
        errors: list[str] = []
        online_targets = self._available_targets(
            include_supabase=include_supabase,
            include_main_pg=include_main_pg,
        )
        for label, _target_key, target in online_targets:
            try:
                existing = target.find_existing_reading(payload["consumer_id"], payload["reading_date"])
                if existing:
                    return existing, errors
            except Exception as exc:
                errors.append(f"{label}: {exc}")

        return None, errors

    def loadAssignedConsumers(
        self,
        meter_reader_id: object | None = None,
        zone_name: str | None = None,
    ) -> list[dict]:
        effective_zone_name = zone_name
        if zone_name is None and isinstance(meter_reader_id, str) and not meter_reader_id.isdigit():
            effective_zone_name = meter_reader_id
        effective_meter_reader_id = None if (isinstance(meter_reader_id, str) and not meter_reader_id.isdigit()) else meter_reader_id
        date_from, date_to = _device_schedule_window()
        if self.remote and self.remote.is_online():
            try:
                schedules = []
                if effective_meter_reader_id not in (None, ""):
                    schedules = self.remote.load_reading_schedules(effective_meter_reader_id, date_from, date_to, "Scheduled")
                    self.local.cache_reading_schedules(schedules, effective_meter_reader_id, date_from, date_to)
                data = self.remote.load_assigned_consumers(effective_meter_reader_id, effective_zone_name, date_from, date_to)
                data = self._overlay_main_pg_rates_for_consumers(data)
                self.local.cache_consumers(data)
                self.local.log_audit(None, "success", "Loaded assigned consumers from Supabase", {"count": len(data), "schedule_count": len(schedules)})
                return data
            except Exception as exc:
                self.local.log_audit(None, "failed", f"Supabase load failed, fallback to cache: {exc}")
        if self.main_pg:
            try:
                schedules = []
                if effective_meter_reader_id not in (None, ""):
                    schedules = self.main_pg.load_reading_schedules(effective_meter_reader_id, date_from, date_to, "Scheduled")
                    self.local.cache_reading_schedules(schedules, effective_meter_reader_id, date_from, date_to)
                data = self.main_pg.load_assigned_consumers(effective_meter_reader_id, effective_zone_name, date_from, date_to)
                data = self._overlay_main_pg_rates_for_consumers(data)
                self.local.cache_consumers(data)
                self.local.log_audit(None, "success", "Loaded assigned consumers from MAIN_PG", {"count": len(data), "schedule_count": len(schedules)})
                return data
            except Exception as exc:
                self.local.log_audit(None, "failed", f"MAIN_PG load failed, fallback to cache: {exc}")
        cached = self.local.load_cached_consumers(effective_zone_name)
        self.local.log_audit(None, "success", "Loaded assigned consumers from local cache", {"count": len(cached)})
        return cached

    def authenticateMeterReader(self, username: str, password: str) -> dict:
        auth_errors: list[tuple[str, Exception]] = []
        for label, client in (("Supabase", self.remote), ("MAIN_PG", self.main_pg)):
            if not client:
                continue
            try:
                if hasattr(client, "is_online") and not client.is_online():
                    continue
                return client.authenticate_meter_reader(username, password)
            except (ValueError, PermissionError) as exc:
                auth_errors.append((label, exc))
            except Exception as exc:
                auth_errors.append((label, exc))

        for _label, exc in auth_errors:
            if isinstance(exc, PermissionError):
                raise exc
        for _label, exc in auth_errors:
            if isinstance(exc, ValueError):
                raise exc
        if auth_errors:
            raise RuntimeError("; ".join(f"{label}: {exc}" for label, exc in auth_errors))
        raise RuntimeError("No central account source is available for meter reader login.")

    def _normalize_reading(self, payload: dict) -> dict:
        reading = dict(payload)
        reading.setdefault("reading_id", str(uuid.uuid4()))
        reading.setdefault("operation_id", str(uuid.uuid4()))
        reading.setdefault("created_at", _utc_now_iso())
        reading.setdefault("updated_at", _utc_now_iso())
        if "reading_date" not in reading:
            reading["reading_date"] = datetime.now(timezone.utc).date().isoformat()
        return reading

    def _queue_for_sync(self, operation: str, reading: dict) -> dict:
        return self.local.enqueue_operation(
            operation,
            reading,
            supabase_status="pending",
            main_pg_status="pending" if self.main_pg else "skipped",
        )

    def queueMeterReading(self, payload: dict) -> dict:
        reading = self._normalize_reading(payload)
        reading = self._overlay_main_pg_rates_for_reading(reading)
        queued = self._queue_for_sync("create", reading)
        self.local.log_audit(queued["id"], "pending", "Queued reading for manual sync", reading)
        return {"status": "queued", "queue": queued, "reading": reading}

    def saveMeterReading(self, payload: dict) -> dict:
        reading = self._normalize_reading(payload)
        reading = self._overlay_main_pg_rates_for_reading(reading)
        queued = self._queue_for_sync("create", reading)
        results, errors = self._sync_reading_to_targets(reading, include_supabase=True, include_main_pg=False)
        if results:
            self.local.mark_target_synced(queued["id"], "supabase")
            if errors:
                self.local.log_audit(queued["id"], "success", f"Reading synced with partial target failures: {'; '.join(errors)}", {"reading_id": reading["reading_id"], "targets": list(results.keys())})
            else:
                self.local.log_audit(queued["id"], "success", "Reading synced to Supabase; MAIN_PG waits for manual sync", {"reading_id": reading["reading_id"], "targets": list(results.keys())})
            return {"status": "synced", "remote": results, "reading": reading, "errors": errors, "queue": queued}
        if errors:
            self.local.mark_target_failed(queued["id"], "supabase", "; ".join(errors))
            self.local.log_audit(queued["id"], "failed", f"Supabase save failed, queued for retry: {'; '.join(errors)}", reading)
        self.local.log_audit(queued["id"], "pending", "Queued offline create operation", reading)
        return {"status": "queued", "queue": queued, "reading": reading}

    def updateMeterReading(self, payload: dict) -> dict:
        reading = self._normalize_reading(payload)
        reading = self._overlay_main_pg_rates_for_reading(reading)
        queued = self._queue_for_sync("update", reading)
        results, errors = self._sync_reading_to_targets(reading, include_supabase=True, include_main_pg=False)
        if results:
            self.local.mark_target_synced(queued["id"], "supabase")
            if errors:
                self.local.log_audit(queued["id"], "success", f"Reading update synced with partial target failures: {'; '.join(errors)}", {"reading_id": reading["reading_id"], "targets": list(results.keys())})
            else:
                self.local.log_audit(queued["id"], "success", "Reading update synced to Supabase; MAIN_PG waits for manual sync", {"reading_id": reading["reading_id"], "targets": list(results.keys())})
            return {"status": "synced", "remote": results, "reading": reading, "errors": errors, "queue": queued}
        if errors:
            self.local.mark_target_failed(queued["id"], "supabase", "; ".join(errors))
            self.local.log_audit(queued["id"], "failed", f"Supabase update failed, queued for retry: {'; '.join(errors)}", reading)
        self.local.log_audit(queued["id"], "pending", "Queued offline update operation", reading)
        return {"status": "queued", "queue": queued, "reading": reading}

    def listPendingSyncReadings(self) -> list[dict]:
        return self.local.list_pending()

    def listPendingSupabaseReadings(self) -> list[dict]:
        return self.local.list_pending("supabase")

    def get_recent_audit_entries(self, limit: int = 20) -> list[dict]:
        return self.local.get_recent_audit(limit=limit)

    def get_last_successful_sync_time(self) -> str | None:
        entries = self.local.get_recent_audit(limit=100)
        for row in entries:
            status = str(row.get("status", "")).lower()
            msg = str(row.get("message", "")).lower()
            if status == "success" and "synced" in msg:
                created = row.get("created_at")
                return str(created) if created else None
        return None

    def get_sync_snapshot(self) -> dict:
        pending = self.listPendingSyncReadings()
        remote_online = self.is_online()
        pg_online = self._main_pg_online()
        if remote_online:
            status = "Online"
        elif pg_online:
            status = "Partial"
        else:
            status = "Offline"
        has_failed = any(row.get("status") == "failed" for row in pending)
        supabase_pending = [
            row for row in pending
            if str(row.get("supabase_status", "")).lower() in {"pending", "failed"}
        ]
        main_pg_pending = [
            row for row in pending
            if str(row.get("main_pg_status", "")).lower() in {"pending", "failed"}
        ]
        main_pg_conflicts = [
            row for row in self.local.get_recent_audit(limit=100)
            if str(row.get("status", "")).lower() == "conflict"
            and "main_pg" in str(row.get("message", "")).lower()
        ]
        if supabase_pending:
            save_target = "Local SQLite Queue (Supabase retry pending)"
        elif status == "Online":
            save_target = "Supabase auto-sync on change"
        elif status == "Partial":
            save_target = "MAIN_PG available, Supabase offline"
        else:
            save_target = "Local SQLite Queue (offline)"
        if not self.main_pg:
            backup_state = "Manual MAIN_PG sync not configured"
        elif main_pg_conflicts:
            backup_state = "MAIN_PG conflicts need review"
        elif main_pg_pending:
            backup_state = "MAIN_PG manual sync needed"
        elif pg_online:
            backup_state = "Backed up to MAIN_PG"
        else:
            backup_state = "MAIN_PG unavailable"
        last_sync = self.get_last_successful_sync_time()
        supabase_last_sync = None
        for row in self.local.get_recent_audit(limit=100):
            msg = str(row.get("message", "")).lower()
            status_text = str(row.get("status", "")).lower()
            if status_text == "success" and "supabase" in msg:
                supabase_last_sync = str(row.get("created_at")) if row.get("created_at") else None
                break
        return {
            "status": status,
            "pending_count": len(pending),
            "has_failed": has_failed,
            "save_target": save_target,
            "backup_state": backup_state,
            "last_sync_time": last_sync,
            "supabase_online": remote_online,
            "supabase_pending_count": len(supabase_pending),
            "supabase_last_sync_time": supabase_last_sync,
            "main_pg_online": pg_online,
            "main_pg_pending_count": len(main_pg_pending),
        }

    def syncPendingReadings(self, include_main_pg: bool = False) -> dict:
        if not self.is_online() and not (include_main_pg and self._main_pg_online()):
            self.local.log_audit(None, "failed", "Sync skipped, offline")
            return {"status": "offline", "synced": 0, "failed": 0, "conflicts": 0}

        pending = self.local.list_pending(None if include_main_pg else "supabase")
        self.local.log_audit(
            None,
            "pending",
            "Starting sync cycle",
            {
                "include_main_pg": include_main_pg,
                "internet_online": self.is_online(),
                "main_pg_online": self._main_pg_online() if include_main_pg else False,
                "pending_count": len(pending),
            },
        )
        synced = 0
        failed = 0
        conflicts = 0

        for row in pending:
            queue_id = row["id"]
            payload = self._overlay_main_pg_rates_for_reading(dict(row["payload"]))
            try:
                row_synced = False
                requested_targets = []
                if str(row.get("supabase_status", "")).lower() in {"pending", "failed"}:
                    requested_targets.append(("Supabase", "supabase", True, False))
                if include_main_pg and str(row.get("main_pg_status", "")).lower() in {"pending", "failed"}:
                    requested_targets.append(("MAIN_PG", "main_pg", False, True))

                for label, target_key, wants_supabase, wants_main_pg in requested_targets:
                    existing, lookup_errors = self._find_existing_reading_with_fallback(
                        payload,
                        include_supabase=wants_supabase,
                        include_main_pg=wants_main_pg,
                    )
                    if existing and existing.get("updated_at") and payload.get("updated_at"):
                        if str(existing["updated_at"]) > str(payload["updated_at"]):
                            reason = "Server has newer reading for same consumer/date."
                            self.local.mark_conflict(queue_id, reason, existing, target=target_key)
                            self.local.log_audit(queue_id, "conflict", f"{label}: {reason}", {"local": payload, "server": existing})
                            conflicts += 1
                            continue

                    results, errors = self._sync_reading_to_targets(
                        payload,
                        include_supabase=wants_supabase,
                        include_main_pg=wants_main_pg,
                    )
                    errors = [*lookup_errors, *errors]
                    if not results:
                        raise RuntimeError("; ".join(errors) if errors else f"{label} did not accept the queue row.")
                    self.local.mark_target_synced(queue_id, target_key)
                    message = f"{label} synced"
                    if errors:
                        message += f" with partial target failures: {'; '.join(errors)}"
                    self.local.log_audit(queue_id, "success", message, {"payload": payload, "targets": list(results.keys())})
                    row_synced = True
                if row_synced:
                    synced += 1
            except ValueError as exc:
                self.local.mark_conflict(queue_id, str(exc))
                self.local.log_audit(queue_id, "conflict", f"Queue row invalid for remote sync: {exc}", payload)
                conflicts += 1
            except Exception as exc:
                failed_targets = []
                if str(row.get("supabase_status", "")).lower() in {"pending", "failed"}:
                    failed_targets.append("supabase")
                if include_main_pg and str(row.get("main_pg_status", "")).lower() in {"pending", "failed"}:
                    failed_targets.append("main_pg")
                for target_key in failed_targets:
                    self.local.mark_target_failed(queue_id, target_key, str(exc))
                self.local.log_audit(queue_id, "failed", f"Queue row sync failed: {exc}", payload)
                failed += 1

        result = {"status": "done", "synced": synced, "failed": failed, "conflicts": conflicts}
        self.local.log_audit(None, "success", "Finished sync cycle", result)
        return result

    def start_sync_worker(self, interval_seconds: int = BACKGROUND_SYNC_INTERVAL_SECONDS) -> None:
        if self._worker and self._worker.is_alive():
            return

        self._worker_stop.clear()

        def _run():
            while not self._worker_stop.is_set():
                try:
                    self.syncPendingReadings(include_main_pg=False)
                except Exception as exc:
                    self.local.log_audit(None, "failed", f"Background sync worker error: {exc}")
                time.sleep(max(60, interval_seconds))

        self._worker = threading.Thread(target=_run, daemon=True, name="handheld-sync-worker")
        self._worker.start()

    def stop_sync_worker(self) -> None:
        self._worker_stop.set()

"""
database.py – SQLite helper for the Water Meter Reader application.
Uses Python's built-in sqlite3 module (no extra install needed).
"""

import os
import hashlib
import hmac
import re
import sqlite3
from datetime import date, datetime
from decimal import Decimal

sqlite3.register_adapter(Decimal, float)

DB_NAME = "meter.db"


def _hash_cached_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        str(password).encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt${salt.hex()}${derived.hex()}"


def _verify_cached_password(password: str, stored: str) -> bool:
    stored_text = str(stored or "")
    if not stored_text.startswith("scrypt$"):
        return hmac.compare_digest(stored_text, str(password))
    try:
        _, salt_hex, expected_hex = stored_text.split("$", 2)
        derived = hashlib.scrypt(
            str(password).encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=16384,
            r=8,
            p=1,
            dklen=len(bytes.fromhex(expected_hex)),
        )
        return hmac.compare_digest(derived.hex(), expected_hex.lower())
    except (TypeError, ValueError):
        return False


def _db_path():
    """Return the absolute path to the database file in the data folder."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", DB_NAME)


def get_connection():
    """Return a new connection to the database with foreign keys enabled."""
    conn = sqlite3.connect(_db_path(), timeout=15.0)
    conn.row_factory = sqlite3.Row          # allows dict-like access on rows
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _sqlite_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _clean_display_name(value) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"unknown", "n/a", "none", "null"}:
        return None
    return " ".join(text.split())


def _ensure_columns(conn: sqlite3.Connection, table_name: str, column_defs: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for name, definition in column_defs.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")


# ─── Schema creation ─────────────────────────────────────────────────────────
def init_db():
    """Create the tables if they don't exist and seed only local user accounts."""
    conn = get_connection()
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS zones (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT    UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS consumers (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            meter_no         TEXT    UNIQUE NOT NULL,
            acct_no          TEXT    NOT NULL,
            name             TEXT    NOT NULL,
            address          TEXT,
            previous_reading INTEGER NOT NULL DEFAULT 0,
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
            latest_reading REAL,
            latest_reading_date TEXT,
            zone_id          INTEGER NOT NULL,
            FOREIGN KEY (zone_id) REFERENCES zones(id)
        );

        CREATE TABLE IF NOT EXISTS readings (
            id              INTEGER  PRIMARY KEY AUTOINCREMENT,
            consumer_id     INTEGER  NOT NULL,
            present_reading INTEGER  NOT NULL,
            consumption     INTEGER  NOT NULL,
            exception       TEXT     DEFAULT 'None',
            reading_date    DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_flagged      BOOLEAN  DEFAULT 0,
            schedule_id     INTEGER,
            schedule_date   TEXT,
            schedule_due_date TEXT,
            billing_cycle   TEXT,
            reading_route_id TEXT,
            assignment_order INTEGER,
            reading_status  TEXT NOT NULL DEFAULT 'valid',
            reading_sync_status TEXT NOT NULL DEFAULT 'pending',
            sync_reading_id TEXT,
            captured_at     TEXT,
            FOREIGN KEY (consumer_id) REFERENCES consumers(id)
        );

        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name     TEXT NOT NULL,
            reader_id TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS receipt_prints (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            consumer_id      INTEGER NOT NULL,
            reading_id       INTEGER,
            acct_no          TEXT,
            consumer_name    TEXT NOT NULL,
            meter_no         TEXT NOT NULL,
            zone_name        TEXT,
            previous_reading INTEGER NOT NULL,
            present_reading  INTEGER NOT NULL,
            consumption      INTEGER NOT NULL,
            exception        TEXT DEFAULT 'None',
            reader_name      TEXT NOT NULL,
            receipt_text     TEXT NOT NULL,
            print_action     TEXT NOT NULL DEFAULT 'print',
            printed_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (consumer_id) REFERENCES consumers(id),
            FOREIGN KEY (reading_id) REFERENCES readings(id)
        );

        CREATE TABLE IF NOT EXISTS current_meter_reader (
            slot INTEGER PRIMARY KEY CHECK (slot = 1),
            account_id INTEGER,
            username TEXT,
            full_name TEXT,
            contact_number TEXT,
            role_id INTEGER,
            account_status TEXT,
            last_login_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reading_schedule (
            schedule_id INTEGER PRIMARY KEY,
            schedule_date TEXT NOT NULL,
            start_date TEXT,
            due_date TEXT,
            billing_month TEXT,
            remote_zone_id INTEGER,
            zone_name TEXT NOT NULL,
            meter_reader_id INTEGER,
            meter_reader_name TEXT,
            meter_reader_contact TEXT,
            status TEXT NOT NULL DEFAULT 'Scheduled',
            cached_consumer_count INTEGER NOT NULL DEFAULT 0,
            cache_verified_at TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reading_assignment (
            schedule_id INTEGER NOT NULL,
            consumer_id INTEGER NOT NULL,
            schedule_date TEXT NOT NULL,
            schedule_due_date TEXT NOT NULL,
            billing_cycle TEXT,
            zone_name TEXT NOT NULL,
            acct_no TEXT,
            assignment_order INTEGER,
            reading_route_id TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            reading_status TEXT NOT NULL DEFAULT 'pending',
            reading_sync_status TEXT NOT NULL DEFAULT 'pending',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (schedule_id, consumer_id),
            FOREIGN KEY (schedule_id) REFERENCES reading_schedule(schedule_id),
            FOREIGN KEY (consumer_id) REFERENCES consumers(id)
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    _ensure_columns(
        conn,
        "readings",
        {
            "schedule_id": "INTEGER",
            "schedule_date": "TEXT",
            "schedule_due_date": "TEXT",
            "billing_cycle": "TEXT",
            "reading_route_id": "TEXT",
            "assignment_order": "INTEGER",
            "reading_status": "TEXT NOT NULL DEFAULT 'valid'",
            "reading_sync_status": "TEXT NOT NULL DEFAULT 'pending'",
            "sync_reading_id": "TEXT",
            "captured_at": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "consumers",
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
            "latest_reading": "REAL",
            "latest_reading_date": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "reading_assignment",
        {
            "acct_no": "TEXT",
            "assignment_order": "INTEGER",
            "reading_route_id": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "users",
        {
            "account_id": "INTEGER",
            "full_name": "TEXT",
            "contact_number": "TEXT",
            "role_id": "INTEGER",
            "account_status": "TEXT",
        },
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_readings_schedule_consumer ON readings(schedule_id, consumer_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_readings_reading_date ON readings(reading_date)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_sync_reading_id ON readings(sync_reading_id) WHERE sync_reading_id IS NOT NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_assignment_deadline ON reading_assignment(schedule_due_date, is_read)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_receipt_prints_printed_at ON receipt_prints(printed_at)")
    _ensure_columns(
        conn,
        "reading_schedule",
        {
            "schedule_date": "TEXT",
            "start_date": "TEXT",
            "due_date": "TEXT",
            "billing_month": "TEXT",
            "remote_zone_id": "INTEGER",
            "zone_name": "TEXT",
            "meter_reader_id": "INTEGER",
            "meter_reader_name": "TEXT",
            "meter_reader_contact": "TEXT",
            "status": "TEXT",
            "cached_consumer_count": "INTEGER NOT NULL DEFAULT 0",
            "cache_verified_at": "TEXT",
            "updated_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
        },
    )

    cur.execute("""
        UPDATE consumers
        SET previous_reading = (
            SELECT r.present_reading
            FROM readings r
            WHERE r.consumer_id = consumers.id
            ORDER BY r.reading_date DESC, r.id DESC
            LIMIT 1
        )
        WHERE EXISTS (
            SELECT 1
            FROM readings r
            WHERE r.consumer_id = consumers.id
        )
    """)

    # ── Seed data (only if tables are empty) ─────────────────────────────
    if False and cur.execute("SELECT COUNT(*) FROM zones").fetchone()[0] == 0:
        zones = ["Zone 1", "Zone 2", "Zone 3"]
        cur.executemany("INSERT INTO zones (name) VALUES (?)",
                        [(z,) for z in zones])

        # Map zone names to their IDs
        zone_ids = {row["name"]: row["id"]
                    for row in cur.execute("SELECT id, name FROM zones")}

        # Sample consumers spread across zones
        consumers = [
            # Zone 1 – 45 consumers
            ("MTR-001", "07-11-46-1", "Maria Santos",      980,  zone_ids["Zone 1"]),
            ("MTR-002", "07-11-46-2", "Juan Dela Cruz",     1234, zone_ids["Zone 1"]),
            ("MTR-003", "07-11-46-3", "Pedro Reyes",        450,  zone_ids["Zone 1"]),
            ("MTR-004", "07-11-46-4", "Ana Garcia",         2100, zone_ids["Zone 1"]),
            ("MTR-005", "07-11-46-5", "Rosa Mendoza",       780,  zone_ids["Zone 1"]),
            ("MTR-006", "07-11-46-6", "Carlos Ramos",       1560, zone_ids["Zone 1"]),
            ("MTR-007", "07-11-46-7", "Elena Torres",       320,  zone_ids["Zone 1"]),
            ("MTR-008", "07-11-46-8", "Roberto Cruz",       890,  zone_ids["Zone 1"]),
            ("MTR-009", "07-11-46-9", "Linda Flores",       1100, zone_ids["Zone 1"]),
            ("MTR-010", "07-11-46-10", "Miguel Bautista",   670,  zone_ids["Zone 1"]),
            # Zone 2 – 30 consumers
            ("MTR-011", "07-12-46-1", "Sofia Villanueva",   540,  zone_ids["Zone 2"]),
            ("MTR-012", "07-12-46-2", "Ramon Aquino",       1890, zone_ids["Zone 2"]),
            ("MTR-013", "07-12-46-3", "Teresa Lim",         410,  zone_ids["Zone 2"]),
            ("MTR-014", "07-12-46-4", "Antonio Pascual",    1350, zone_ids["Zone 2"]),
            ("MTR-015", "07-12-46-5", "Gloria Tan",         920,  zone_ids["Zone 2"]),
            # Zone 3 – 20 consumers
            ("MTR-016", "07-13-46-1", "Fernando Castillo",  760,  zone_ids["Zone 3"]),
            ("MTR-017", "07-13-46-2", "Lucia Rivera",       1440, zone_ids["Zone 3"]),
            ("MTR-018", "07-13-46-3", "Ricardo Morales",    280,  zone_ids["Zone 3"]),
            ("MTR-019", "07-13-46-4", "Carmen Lopez",       1670, zone_ids["Zone 3"]),
            ("MTR-020", "07-13-46-5", "Jose Hernandez",     530,  zone_ids["Zone 3"]),
        ]

        cur.executemany(
            "INSERT INTO consumers (meter_no, acct_no, name, previous_reading, zone_id) VALUES (?, ?, ?, ?, ?)",
            consumers
        )

    # Remove legacy demo credentials; offline users must first authenticate online.
    cur.execute(
        """
        DELETE FROM users
        WHERE account_id IS NULL
          AND ((username = 'reader1' AND reader_id = 'MR-001')
            OR (username = 'reader2' AND reader_id = 'MR-002'))
        """
    )

    conn.commit()
    conn.close()


def seed_default_users():
    """Retained for compatibility; real users are cached after online login."""
    return None


def authenticate_user(username: str, password: str) -> dict | None:
    """Validate cached credentials for offline login."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT username, password, name, reader_id, account_id, full_name, contact_number, role_id, account_status
        FROM users
        WHERE username = ?
        """,
        (username,)
    ).fetchone()
    if row and _verify_cached_password(password, row['password']):
        if not str(row['password'] or '').startswith('scrypt$'):
            conn.execute(
                "UPDATE users SET password = ? WHERE username = ?",
                (_hash_cached_password(password), username),
            )
            conn.commit()
        user = {
            'username': row['username'],
            'name': row['full_name'] or row['name'],
            'full_name': row['full_name'] or row['name'],
            'id': row['account_id'] if row['account_id'] not in (None, "") else row['reader_id'],
            'account_id': row['account_id'],
            'reader_id': row['reader_id'],
            'contact_number': row['contact_number'],
            'role_id': row['role_id'],
            'account_status': row['account_status'] or "Offline Cached",
        }
        conn.close()
        return user
    conn.close()
    return None


def cache_meter_reader_credentials(user: dict, password: str) -> None:
    """Persist a successful meter-reader login locally for offline auth fallback."""
    username = str(user.get("username") or "").strip()
    if not username or password in (None, ""):
        return

    full_name = str(user.get("full_name") or user.get("name") or username).strip()
    reader_id = str(user.get("reader_id") or user.get("account_id") or user.get("id") or username).strip()
    account_id = user.get("account_id", user.get("id"))
    try:
        account_id = int(account_id) if account_id not in (None, "") else None
    except (TypeError, ValueError):
        account_id = None
    role_id = user.get("role_id")
    try:
        role_id = int(role_id) if role_id not in (None, "") else None
    except (TypeError, ValueError):
        role_id = None

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO users (
            username, password, name, reader_id, account_id, full_name, contact_number, role_id, account_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            password = excluded.password,
            name = excluded.name,
            reader_id = excluded.reader_id,
            account_id = excluded.account_id,
            full_name = excluded.full_name,
            contact_number = excluded.contact_number,
            role_id = excluded.role_id,
            account_status = excluded.account_status
        """,
        (
            username,
            _hash_cached_password(str(password)),
            full_name,
            reader_id,
            account_id,
            full_name,
            user.get("contact_number"),
            role_id,
            user.get("account_status") or "Active",
        ),
    )
    conn.commit()
    conn.close()


def get_app_setting(key: str, default=None):
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = ?",
        (str(key),),
    ).fetchone()
    conn.close()
    if row is None:
        return default
    return row["value"]


def set_app_setting(key: str, value) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (str(key), None if value is None else str(value)),
    )
    conn.commit()
    conn.close()


def get_all_users() -> list[dict]:
    """Return all users for login hint display."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT username, name, reader_id FROM users ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_current_meter_reader(user: dict) -> None:
    """Persist the currently logged-in meter reader identity locally."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO current_meter_reader (
            slot, account_id, username, full_name, contact_number, role_id, account_status, last_login_at
        )
        VALUES (1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(slot) DO UPDATE SET
            account_id = excluded.account_id,
            username = excluded.username,
            full_name = excluded.full_name,
            contact_number = excluded.contact_number,
            role_id = excluded.role_id,
            account_status = excluded.account_status,
            last_login_at = CURRENT_TIMESTAMP
        """,
        (
            user.get("account_id"),
            user.get("username"),
            user.get("full_name") or user.get("name"),
            user.get("contact_number"),
            user.get("role_id"),
            user.get("account_status"),
        ),
    )
    conn.commit()
    conn.close()


def get_current_meter_reader() -> dict | None:
    """Return the locally stored meter reader identity."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT account_id, username, full_name, contact_number, role_id, account_status, last_login_at
        FROM current_meter_reader
        WHERE slot = 1
        LIMIT 1
        """
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def clear_current_meter_reader() -> None:
    """Clear the locally stored meter reader identity."""
    conn = get_connection()
    conn.execute("DELETE FROM current_meter_reader WHERE slot = 1")
    conn.commit()
    conn.close()


def _normalize_schedule_date(value) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return raw.split("T", 1)[0].split(" ", 1)[0]


def _effective_schedule_context(
    schedule_date: str | None = None,
    meter_reader_id: int | str | None = None,
) -> tuple[str | None, int | None, bool]:
    effective_reader_id = meter_reader_id
    if effective_reader_id in (None, ""):
        current = get_current_meter_reader() or {}
        effective_reader_id = current.get("account_id")
    try:
        reader_id_int = int(effective_reader_id) if effective_reader_id not in (None, "") else None
    except (TypeError, ValueError):
        reader_id_int = None
    if reader_id_int is None:
        return _normalize_schedule_date(schedule_date), None, False
    normalized_date = _normalize_schedule_date(schedule_date)
    if normalized_date is None:
        normalized_date = date.today().isoformat()
    month_start, month_end = _month_bounds(normalized_date)
    conn = get_connection()
    try:
        has_schedule_rows = conn.execute(
            """
            SELECT 1
            FROM reading_schedule rs
            WHERE rs.meter_reader_id = ?
              AND date(COALESCE(rs.start_date, rs.schedule_date)) <= date(?)
              AND date(COALESCE(rs.due_date, rs.start_date, rs.schedule_date)) >= date(?)
              AND rs.status IN ('Scheduled', 'In Progress')
            LIMIT 1
            """,
            (reader_id_int, month_end, month_start),
        ).fetchone() is not None
    finally:
        conn.close()
    # A known reader is always assignment-filtered. Falling back to every local
    # zone when their schedule cache is empty can expose another reader's route.
    return normalized_date, reader_id_int, True


def _month_bounds(schedule_date: str | None) -> tuple[str, str]:
    normalized = _normalize_schedule_date(schedule_date) or date.today().isoformat()
    anchor = date.fromisoformat(normalized)
    month_start = anchor.replace(day=1)
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1, day=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1, day=1)
    month_end = next_month.fromordinal(next_month.toordinal() - 1)
    return month_start.isoformat(), month_end.isoformat()


def _natural_zone_key(value: str) -> tuple:
    text = str(value or "")
    parts = re.split(r"(\d+)", text.lower())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def account_base_group(value) -> str:
    """Return the first three account-number segments without rewriting the value."""
    parts = str(value or "").strip().split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else str(value or "").strip()


def natural_account_key(value) -> tuple:
    """Naturally order mixed numeric/alphanumeric account-number segments."""
    segments = str(value or "").strip().split("-")
    return tuple(
        tuple((0, int(token)) if token.isdigit() else (1, token.lower())
              for token in re.findall(r"\d+|[^\d]+", segment))
        for segment in segments
    )


def assignment_sort_key(row: dict) -> tuple:
    raw_order = row.get("assignment_order")
    try:
        order_key = (0, float(raw_order)) if raw_order not in (None, "") else (1, 0.0)
    except (TypeError, ValueError):
        order_key = (1, 0.0)
    return (*order_key, natural_account_key(row.get("acct_no")), int(row.get("id") or row.get("consumer_id") or 0))


def sort_and_mark_nearby(rows: list[dict]) -> list[dict]:
    """Sort assignments and annotate accounts sharing the same base group."""
    items = [dict(row) for row in rows]
    counts: dict[str, int] = {}
    for item in items:
        base = account_base_group(item.get("acct_no"))
        if base:
            counts[base] = counts.get(base, 0) + 1
    for item in items:
        base = account_base_group(item.get("acct_no"))
        item["account_base"] = base
        item["is_nearby_connection"] = bool(base and counts.get(base, 0) > 1)
    return sorted(items, key=assignment_sort_key)


def replace_reading_schedules_from_sync(
    schedules: list[dict],
    meter_reader_id: int | str | None,
    date_from: str | None,
    date_to: str | None,
) -> int:
    normalized_from = _normalize_schedule_date(date_from)
    normalized_to = _normalize_schedule_date(date_to)
    try:
        reader_id_int = int(meter_reader_id) if meter_reader_id not in (None, "") else None
    except (TypeError, ValueError):
        reader_id_int = None

    conn = get_connection()
    cur = conn.cursor()

    upserted = 0
    for row in schedules or []:
        if not isinstance(row, dict):
            continue
        schedule_id = row.get("Schedule_ID", row.get("schedule_id"))
        start_date = _normalize_schedule_date(
            row.get("Start_Date", row.get("start_date", row.get("Schedule_Date", row.get("schedule_date"))))
        )
        due_date = _normalize_schedule_date(row.get("Due_Date", row.get("due_date", start_date)))
        schedule_date = start_date
        billing_month = str(row.get("Billing_Month", row.get("billing_month")) or "").strip() or None
        remote_zone_id = row.get("Zone_ID", row.get("zone_id"))
        zone_name = str(row.get("Zone_Name", row.get("zone_name")) or "").strip()
        meter_reader_value = row.get("Meter_Reader_ID", row.get("meter_reader_id", reader_id_int))
        meter_reader_name = row.get("Meter_Reader_Name", row.get("meter_reader_name"))
        meter_reader_contact = row.get("Meter_Reader_Contact", row.get("meter_reader_contact"))
        status = str(row.get("Status", row.get("status")) or "Scheduled").strip() or "Scheduled"
        try:
            schedule_id_int = int(schedule_id)
        except (TypeError, ValueError):
            continue
        try:
            remote_zone_id_int = int(remote_zone_id) if remote_zone_id not in (None, "") else None
        except (TypeError, ValueError):
            remote_zone_id_int = None
        try:
            meter_reader_id_int = int(meter_reader_value) if meter_reader_value not in (None, "") else reader_id_int
        except (TypeError, ValueError):
            meter_reader_id_int = reader_id_int
        if not schedule_date or not zone_name:
            continue
        cur.execute("INSERT OR IGNORE INTO zones (name) VALUES (?)", (zone_name,))
        cur.execute(
            """
            INSERT INTO reading_schedule (
                schedule_id, schedule_date, start_date, due_date, billing_month,
                remote_zone_id, zone_name, meter_reader_id,
                meter_reader_name, meter_reader_contact, status, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(schedule_id) DO UPDATE SET
                schedule_date = excluded.schedule_date,
                start_date = excluded.start_date,
                due_date = excluded.due_date,
                billing_month = excluded.billing_month,
                remote_zone_id = excluded.remote_zone_id,
                zone_name = excluded.zone_name,
                meter_reader_id = excluded.meter_reader_id,
                meter_reader_name = excluded.meter_reader_name,
                meter_reader_contact = excluded.meter_reader_contact,
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                schedule_id_int,
                schedule_date,
                start_date,
                due_date,
                billing_month,
                remote_zone_id_int,
                zone_name,
                meter_reader_id_int,
                meter_reader_name,
                meter_reader_contact,
                status,
            ),
        )
        upserted += 1

    conn.commit()
    conn.close()
    return upserted


def get_assigned_routes(meter_reader_id: int | str | None) -> list[dict]:
    """Return only routes belonging to the signed-in reader, including offline readiness."""
    try:
        reader_id = int(meter_reader_id) if meter_reader_id not in (None, "") else None
    except (TypeError, ValueError):
        reader_id = None
    if reader_id is None:
        return []
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT schedule_id,
               meter_reader_id,
               COALESCE(start_date, schedule_date) AS start_date,
               COALESCE(due_date, start_date, schedule_date) AS due_date,
               billing_month, zone_name, status,
               cached_consumer_count, cache_verified_at,
               (SELECT COUNT(*) FROM reading_assignment ra
                WHERE ra.schedule_id = reading_schedule.schedule_id) AS assignment_count,
               (SELECT COUNT(*) FROM reading_assignment ra
                WHERE ra.schedule_id = reading_schedule.schedule_id AND ra.is_read = 0) AS unread_count,
               CASE
                   WHEN date(COALESCE(due_date, start_date, schedule_date)) < date('now') THEN 'Overdue'
                   WHEN lower(status) IN ('completed', 'cancelled') THEN status
                   ELSE status
               END AS display_status
        FROM reading_schedule
        WHERE meter_reader_id = ?
          AND lower(status) <> 'cancelled'
          AND (
              lower(status) <> 'completed'
              OR EXISTS (
                  SELECT 1 FROM reading_assignment ra
                  WHERE ra.schedule_id = reading_schedule.schedule_id AND ra.is_read = 0
              )
          )
        ORDER BY
          CASE
            WHEN date(COALESCE(start_date, schedule_date)) <= date('now')
             AND date(COALESCE(due_date, start_date, schedule_date)) >= date('now') THEN 0
            WHEN date(COALESCE(start_date, schedule_date)) > date('now') THEN 1
            ELSE 2
          END,
          CASE WHEN date(COALESCE(start_date, schedule_date)) > date('now')
               THEN date(COALESCE(start_date, schedule_date)) END ASC,
          CASE WHEN date(COALESCE(due_date, start_date, schedule_date)) < date('now')
               THEN date(COALESCE(due_date, start_date, schedule_date)) END DESC,
          zone_name, schedule_id
        """,
        (reader_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def mark_route_cache_verified(
    schedule_id: int | str,
    meter_reader_id: int | str,
    consumer_count: int,
) -> bool:
    """Mark a route ready only when it still belongs to this reader and has cached rows."""
    try:
        schedule_id_int = int(schedule_id)
        reader_id_int = int(meter_reader_id)
        count = int(consumer_count)
    except (TypeError, ValueError):
        return False
    if count <= 0:
        return False
    conn = get_connection()
    cur = conn.execute(
        """
        UPDATE reading_schedule
        SET cached_consumer_count = ?, cache_verified_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE schedule_id = ? AND meter_reader_id = ?
        """,
        (count, schedule_id_int, reader_id_int),
    )
    conn.commit()
    changed = cur.rowcount == 1
    conn.close()
    return changed


# ─── Query helpers ────────────────────────────────────────────────────────────

def _attach_assignment_context(conn: sqlite3.Connection, item: dict, schedule_id: int | None) -> dict:
    if schedule_id is None or not item:
        return item
    assignment = conn.execute(
        """
        SELECT schedule_id, consumer_id, schedule_date, schedule_due_date, billing_cycle,
               zone_name, acct_no, assignment_order, reading_route_id,
               is_read, reading_status, reading_sync_status
        FROM reading_assignment
        WHERE schedule_id = ? AND consumer_id = ?
        LIMIT 1
        """,
        (schedule_id, int(item.get("id") or item.get("consumer_id"))),
    ).fetchone()
    if assignment:
        context = dict(assignment)
        if context.get("acct_no") not in (None, ""):
            item["acct_no"] = context["acct_no"]
        context.pop("acct_no", None)
        item.update(context)
    return item


def search_consumer(
    meter_no: str,
    unread_only: bool = True,
    schedule_date: str | None = None,
    meter_reader_id: int | str | None = None,
    schedule_id: int | str | None = None,
) -> dict | None:
    """Look up a consumer by meter/account/name. Returns dict or None."""
    conn = get_connection()
    normalized = "".join(ch for ch in str(meter_no or "") if ch.isalnum())
    effective_date, effective_reader_id, use_schedule_filter = _effective_schedule_context(schedule_date, meter_reader_id)
    month_start, month_end = _month_bounds(effective_date)
    sql = """SELECT c.id, c.meter_no, c.acct_no, c.name, c.address, c.previous_reading,
                    c.latest_reading,
                    COALESCE(
                        c.latest_reading_date,
                        (
                            SELECT MAX(date(r_prev.reading_date))
                            FROM readings r_prev
                            WHERE r_prev.consumer_id = c.id
                        )
                    ) AS latest_reading_date,
                    c.classification_id, c.classification_name, c.minimum_cubic,
                    c.minimum_rate, c.excess_rate_per_cubic, c.due_days, c.penalty_percent,
                    c.billing_month, c.date_covered_from, c.date_covered_to,
                    c.amount_due, c.previous_balance, c.due_date, c.penalty, c.previous_penalty, c.total_after_due_date,
                    c.bill_status, c.late_fee,
                    z.name AS zone_name
             FROM consumers c
             JOIN zones z ON c.zone_id = z.id
             WHERE (
                 c.meter_no = ?
                 OR c.acct_no = ?
                 OR c.name = ?
                 OR REPLACE(REPLACE(c.meter_no, '-', ''), ' ', '') = ?
                 OR REPLACE(REPLACE(c.acct_no, '-', ''), ' ', '') = ?
             )"""
    params: list[object] = [meter_no, meter_no, meter_no, normalized, normalized]
    try:
        selected_schedule_id = int(schedule_id) if schedule_id not in (None, "") else None
    except (TypeError, ValueError):
        selected_schedule_id = None
    if use_schedule_filter and selected_schedule_id is not None:
        sql += """
               AND EXISTS (
                   SELECT 1 FROM reading_assignment ra
                   WHERE ra.consumer_id = c.id AND ra.schedule_id = ?
               )
        """
        params.append(selected_schedule_id)
    elif use_schedule_filter:
        sql += """
               AND EXISTS (
                   SELECT 1
                   FROM reading_schedule rs
                   WHERE rs.zone_name = z.name
                     AND rs.meter_reader_id = ?
                     AND date(COALESCE(rs.start_date, rs.schedule_date)) <= date(?)
                     AND date(COALESCE(rs.due_date, rs.start_date, rs.schedule_date)) >= date(?)
                     AND rs.status IN ('Scheduled', 'In Progress')
               )
        """
        params.extend([effective_reader_id, month_end, month_start])
    if unread_only:
        if use_schedule_filter and selected_schedule_id is not None:
            sql += """
               AND EXISTS (
                   SELECT 1 FROM reading_assignment ra
                   WHERE ra.consumer_id = c.id AND ra.schedule_id = ? AND ra.is_read = 0
               )
            """
            params.append(selected_schedule_id)
        elif use_schedule_filter:
            sql += """
               AND NOT EXISTS (
                   SELECT 1
                   FROM readings r
                   WHERE r.consumer_id = c.id
                     AND date(r.reading_date) >= date(?)
                     AND date(r.reading_date) <= date(?)
               )
               AND NOT (
                   c.latest_reading_date IS NOT NULL
                   AND date(c.latest_reading_date) >= date(?)
                   AND date(c.latest_reading_date) <= date(?)
               )
            """
            params.extend([month_start, month_end, month_start, month_end])
        else:
            sql += """
               AND NOT EXISTS (
                   SELECT 1 FROM readings r WHERE r.consumer_id = c.id
               )
            """
    sql += """
             ORDER BY CASE
                 WHEN c.meter_no = ? THEN 0
                 WHEN c.acct_no = ? THEN 1
                 WHEN c.name = ? THEN 2
                 WHEN REPLACE(REPLACE(c.meter_no, '-', ''), ' ', '') = ? THEN 3
                 WHEN REPLACE(REPLACE(c.acct_no, '-', ''), ' ', '') = ? THEN 4
                 ELSE 5
             END
             LIMIT 1"""
    params = (
        *params,
        meter_no, meter_no, meter_no, normalized, normalized,
    )
    row = conn.execute(sql, params).fetchone()
    data = _attach_assignment_context(conn, dict(row), selected_schedule_id) if row else None
    conn.close()
    return data


def get_consumer_by_id(
    consumer_id: int | str,
    schedule_date: str | None = None,
    meter_reader_id: int | str | None = None,
    schedule_id: int | str | None = None,
) -> dict | None:
    """Look up a consumer by exact local/remote consumer id."""
    conn = get_connection()
    effective_date, effective_reader_id, use_schedule_filter = _effective_schedule_context(schedule_date, meter_reader_id)
    month_start, month_end = _month_bounds(effective_date)
    sql = """SELECT c.id, c.meter_no, c.acct_no, c.name, c.address, c.previous_reading,
                    c.latest_reading,
                    COALESCE(
                        c.latest_reading_date,
                        (
                            SELECT MAX(date(r_prev.reading_date))
                            FROM readings r_prev
                            WHERE r_prev.consumer_id = c.id
                        )
                    ) AS latest_reading_date,
                    c.classification_id, c.classification_name, c.minimum_cubic,
                    c.minimum_rate, c.excess_rate_per_cubic, c.due_days, c.penalty_percent,
                    c.billing_month, c.date_covered_from, c.date_covered_to,
                    c.amount_due, c.previous_balance, c.due_date, c.penalty, c.previous_penalty, c.total_after_due_date,
                    c.bill_status, c.late_fee,
                    z.name AS zone_name
             FROM consumers c
             JOIN zones z ON c.zone_id = z.id
             WHERE c.id = ?"""
    params: list[object] = [int(consumer_id)]
    try:
        selected_schedule_id = int(schedule_id) if schedule_id not in (None, "") else None
    except (TypeError, ValueError):
        selected_schedule_id = None
    if use_schedule_filter and selected_schedule_id is not None:
        sql += """
               AND EXISTS (
                   SELECT 1 FROM reading_assignment ra
                   WHERE ra.consumer_id = c.id AND ra.schedule_id = ?
               )
        """
        params.append(selected_schedule_id)
    elif use_schedule_filter:
        sql += """
               AND EXISTS (
                   SELECT 1
                   FROM reading_schedule rs
                   WHERE rs.zone_name = z.name
                     AND rs.meter_reader_id = ?
                     AND date(COALESCE(rs.start_date, rs.schedule_date)) <= date(?)
                     AND date(COALESCE(rs.due_date, rs.start_date, rs.schedule_date)) >= date(?)
                     AND rs.status IN ('Scheduled', 'In Progress')
               )
        """
        params.extend([effective_reader_id, month_end, month_start])
    sql += " LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    data = _attach_assignment_context(conn, dict(row), selected_schedule_id) if row else None
    conn.close()
    return data



def search_consumers_by_zone(
    query: str,
    zone_name: str,
    limit: int = 8,
    unread_only: bool = True,
    schedule_date: str | None = None,
    meter_reader_id: int | str | None = None,
    schedule_id: int | str | None = None,
) -> list[dict]:
    """Search consumers by partial meter_no or name, filtered to a specific zone."""
    conn = get_connection()
    like_pattern = f"%{query}%"
    normalized = "".join(ch for ch in str(query or "") if ch.isalnum())
    normalized_like = f"%{normalized}%"
    effective_date, effective_reader_id, use_schedule_filter = _effective_schedule_context(schedule_date, meter_reader_id)
    month_start, month_end = _month_bounds(effective_date)
    sql = """SELECT c.id, c.meter_no, c.acct_no, c.name, c.address, c.previous_reading,
                    c.latest_reading,
                    COALESCE(
                        c.latest_reading_date,
                        (
                            SELECT MAX(date(r_prev.reading_date))
                            FROM readings r_prev
                            WHERE r_prev.consumer_id = c.id
                        )
                    ) AS latest_reading_date,
                    c.classification_id, c.classification_name, c.minimum_cubic,
                    c.minimum_rate, c.excess_rate_per_cubic, c.due_days, c.penalty_percent,
                    c.billing_month, c.date_covered_from, c.date_covered_to,
                    c.amount_due, c.previous_balance, c.due_date, c.penalty, c.previous_penalty, c.total_after_due_date,
                    c.bill_status, c.late_fee,
                    z.name AS zone_name
             FROM consumers c
             JOIN zones z ON c.zone_id = z.id
             WHERE z.name = ?
               AND (
                   c.meter_no LIKE ?
                   OR c.acct_no LIKE ?
                   OR c.name LIKE ?
                   OR REPLACE(REPLACE(c.meter_no, '-', ''), ' ', '') LIKE ?
                   OR REPLACE(REPLACE(c.acct_no, '-', ''), ' ', '') LIKE ?
               )"""
    params: list[object] = [zone_name, like_pattern, like_pattern, like_pattern, normalized_like, normalized_like]
    try:
        selected_schedule_id = int(schedule_id) if schedule_id not in (None, "") else None
    except (TypeError, ValueError):
        selected_schedule_id = None
    if use_schedule_filter and selected_schedule_id is not None:
        sql += """
               AND EXISTS (
                   SELECT 1 FROM reading_assignment ra
                   WHERE ra.consumer_id = c.id AND ra.schedule_id = ?
               )
        """
        params.append(selected_schedule_id)
    elif use_schedule_filter:
        sql += """
               AND EXISTS (
                   SELECT 1
                   FROM reading_schedule rs
                   WHERE rs.zone_name = z.name
                     AND rs.meter_reader_id = ?
                     AND date(COALESCE(rs.start_date, rs.schedule_date)) <= date(?)
                     AND date(COALESCE(rs.due_date, rs.start_date, rs.schedule_date)) >= date(?)
                     AND rs.status IN ('Scheduled', 'In Progress')
               )
        """
        params.extend([effective_reader_id, month_end, month_start])
    if unread_only:
        if use_schedule_filter and selected_schedule_id is not None:
            sql += """
               AND EXISTS (
                   SELECT 1 FROM reading_assignment ra
                   WHERE ra.consumer_id = c.id AND ra.schedule_id = ? AND ra.is_read = 0
               )
            """
            params.append(selected_schedule_id)
        elif use_schedule_filter:
            sql += """
               AND NOT EXISTS (
                   SELECT 1 FROM readings r
                   WHERE r.consumer_id = c.id
                     AND date(r.reading_date) >= date(?)
                     AND date(r.reading_date) <= date(?)
               )
               AND NOT (
                   c.latest_reading_date IS NOT NULL
                   AND date(c.latest_reading_date) >= date(?)
                   AND date(c.latest_reading_date) <= date(?)
               )
            """
            params.extend([month_start, month_end, month_start, month_end])
        else:
            sql += """
               AND NOT EXISTS (
                   SELECT 1 FROM readings r WHERE r.consumer_id = c.id
               )
            """
    if selected_schedule_id is None:
        sql += " ORDER BY c.meter_no LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, tuple(params)).fetchall()
    results = [
        _attach_assignment_context(conn, dict(row), selected_schedule_id)
        for row in rows
    ]
    conn.close()
    if selected_schedule_id is not None:
        return sort_and_mark_nearby(results)[:limit]
    return sort_and_mark_nearby(results)


def save_reading(
    consumer_id: int,
    present_reading: float,
    consumption: float,
    exception: str = "None",
    is_flagged: bool = False,
    reading_date: str | None = None,
    *,
    schedule_id: int | str | None = None,
    schedule_date: str | None = None,
    schedule_due_date: str | None = None,
    billing_cycle: str | None = None,
    reading_route_id: int | str | None = None,
    assignment_order: int | str | None = None,
    reading_status: str = "valid",
    reading_sync_status: str = "pending",
    sync_reading_id: str | None = None,
    captured_at: str | None = None,
):
    """Insert a reading and attach it to the exact field assignment when available."""
    conn = get_connection()
    cur = conn.cursor()
    normalized_status = str(reading_status or "valid").strip().lower()
    normalized_sync = str(reading_sync_status or "pending").strip().lower()
    try:
        normalized_assignment_order = int(float(assignment_order)) if assignment_order not in (None, "") else None
    except (TypeError, ValueError):
        normalized_assignment_order = None
    captured = captured_at or datetime.now().astimezone().isoformat()
    cur.execute(
        """
        INSERT INTO readings (
            consumer_id, present_reading, consumption, exception, is_flagged, reading_date,
            schedule_id, schedule_date, schedule_due_date, billing_cycle,
            reading_route_id, assignment_order,
            reading_status, reading_sync_status, sync_reading_id, captured_at
        ) VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            consumer_id, present_reading, consumption, exception, 1 if is_flagged else 0, reading_date,
            int(schedule_id) if schedule_id not in (None, "") else None,
            _normalize_schedule_date(schedule_date), _normalize_schedule_date(schedule_due_date),
            str(billing_cycle or "").strip() or None,
            str(reading_route_id) if reading_route_id not in (None, "") else None,
            normalized_assignment_order,
            normalized_status, normalized_sync,
            str(sync_reading_id or "").strip() or None, captured,
        ),
    )
    effective_reading_date = str(reading_date).strip() if reading_date else date.today().isoformat()
    conn.execute(
        """
        UPDATE consumers
        SET previous_reading = ?,
            latest_reading = ?,
            latest_reading_date = ?
        WHERE id = ?
        """,
        (present_reading, present_reading, effective_reading_date, consumer_id),
    )
    if schedule_id not in (None, ""):
        is_valid = normalized_status not in {"rejected", "deleted", "invalid"}
        conn.execute(
            """
            UPDATE reading_assignment
            SET is_read = ?, reading_status = ?, reading_sync_status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE schedule_id = ? AND consumer_id = ?
            """,
            (1 if is_valid else 0, normalized_status, normalized_sync, int(schedule_id), int(consumer_id)),
        )
    conn.commit()
    reading_id = cur.lastrowid
    conn.close()
    return reading_id


def update_reading_sync_state(
    sync_reading_id: str,
    sync_status: str,
    reading_status: str | None = None,
) -> bool:
    """Update the local reading and its assignment after a queue/sync outcome."""
    key = str(sync_reading_id or "").strip()
    if not key:
        return False
    conn = get_connection()
    row = conn.execute(
        "SELECT id, consumer_id, schedule_id, reading_status FROM readings WHERE sync_reading_id = ? LIMIT 1",
        (key,),
    ).fetchone()
    if not row:
        conn.close()
        return False
    normalized_sync = str(sync_status or "pending").strip().lower()
    normalized_reading = str(reading_status or row["reading_status"] or "valid").strip().lower()
    conn.execute(
        "UPDATE readings SET reading_sync_status = ?, reading_status = ? WHERE id = ?",
        (normalized_sync, normalized_reading, row["id"]),
    )
    if row["schedule_id"] is not None:
        valid = normalized_reading not in {"rejected", "deleted", "invalid"}
        conn.execute(
            """
            UPDATE reading_assignment
            SET is_read = ?, reading_status = ?, reading_sync_status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE schedule_id = ? AND consumer_id = ?
            """,
            (1 if valid else 0, normalized_reading, normalized_sync, row["schedule_id"], row["consumer_id"]),
        )
    conn.commit()
    conn.close()
    return True


def save_receipt_print(
    consumer_id: int,
    receipt_text: str,
    previous_reading: float,
    present_reading: float,
    consumption: float,
    exception: str = "None",
    reader_name: str = "Field Reader",
    reading_id: int | None = None,
    print_action: str = "print",
    acct_no: str | None = None,
    consumer_name: str | None = None,
    meter_no: str | None = None,
    zone_name: str | None = None,
) -> int:
    """Persist a printed receipt snapshot for later tracing and reprinting."""
    conn = get_connection()
    cur = conn.cursor()
    consumer_row = conn.execute(
        "SELECT acct_no, name, meter_no FROM consumers WHERE id = ? LIMIT 1",
        (int(consumer_id),),
    ).fetchone()
    resolved_acct_no = acct_no or (consumer_row["acct_no"] if consumer_row else None)
    resolved_consumer_name = _clean_display_name(consumer_name) or _clean_display_name(consumer_row["name"] if consumer_row else None)
    resolved_meter_no = meter_no or (consumer_row["meter_no"] if consumer_row else None)
    cur.execute(
        """
        INSERT INTO receipt_prints (
            consumer_id, reading_id, acct_no, consumer_name, meter_no, zone_name,
            previous_reading, present_reading, consumption, exception, reader_name,
            receipt_text, print_action
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            consumer_id,
            reading_id,
            resolved_acct_no,
            resolved_consumer_name or "Unknown",
            resolved_meter_no or "N/A",
            zone_name,
            previous_reading,
            present_reading,
            consumption,
            exception or "None",
            reader_name or "Field Reader",
            receipt_text,
            print_action or "print",
        ),
    )
    conn.commit()
    receipt_print_id = cur.lastrowid
    conn.close()
    return receipt_print_id


def update_consumer_due_date(consumer_id: int, due_date: str) -> None:
    """Persist a manually adjusted due date for a consumer's local billing snapshot."""
    conn = get_connection()
    conn.execute(
        "UPDATE consumers SET due_date = ? WHERE id = ?",
        (str(due_date).strip(), int(consumer_id)),
    )
    conn.commit()
    conn.close()


def get_latest_receipt_print(consumer_id: int | None = None) -> dict | None:
    """Return the most recent saved receipt print, optionally for one consumer."""
    conn = get_connection()
    sql = """
        SELECT
            rp.*,
            c.id AS resolved_consumer_id,
            c.meter_no AS resolved_meter_no,
            c.acct_no AS resolved_acct_no,
            c.name AS resolved_consumer_name,
            z.name AS resolved_zone_name
        FROM receipt_prints rp
        LEFT JOIN consumers c ON c.id = rp.consumer_id
        LEFT JOIN zones z ON z.id = c.zone_id
    """
    params = ()
    if consumer_id is not None:
        sql += " WHERE rp.consumer_id = ?"
        params = (consumer_id,)
    sql += " ORDER BY rp.printed_at DESC, rp.id DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    data["consumer_id"] = data.get("consumer_id") or data.get("resolved_consumer_id")
    data["meter_no"] = data.get("meter_no") or data.get("resolved_meter_no")
    data["acct_no"] = data.get("acct_no") or data.get("resolved_acct_no")
    data["consumer_name"] = data.get("consumer_name") or data.get("resolved_consumer_name")
    data["zone_name"] = data.get("zone_name") or data.get("resolved_zone_name")
    return data


def list_receipt_print_history(
    search_text: str = "",
    month: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Return persisted receipt history, optionally filtered by reading month."""
    conn = get_connection()
    sql = """
        SELECT
            rp.*,
            COALESCE(r.reading_date, rp.printed_at) AS history_date,
            strftime('%Y-%m', COALESCE(r.reading_date, rp.printed_at)) AS history_month,
            (
                SELECT COUNT(*)
                FROM receipt_prints rp_count
                WHERE rp_count.consumer_id = rp.consumer_id
                  AND COALESCE(rp_count.reading_id, -1) = COALESCE(rp.reading_id, -1)
            ) AS print_count,
            (
                SELECT COUNT(*)
                FROM receipt_prints rp_count
                WHERE rp_count.consumer_id = rp.consumer_id
                  AND COALESCE(rp_count.reading_id, -1) = COALESCE(rp.reading_id, -1)
                  AND rp_count.print_action = 'reprint'
            ) AS reprint_count
        FROM receipt_prints rp
        LEFT JOIN readings r ON r.id = rp.reading_id
    """
    params: list[object] = []
    conditions: list[str] = []
    trimmed = (search_text or "").strip()
    if trimmed:
        like = f"%{trimmed}%"
        conditions.append("""(
               CAST(rp.id AS TEXT) LIKE ?
               OR COALESCE(rp.acct_no, '') LIKE ?
               OR COALESCE(rp.consumer_name, '') LIKE ?
               OR COALESCE(rp.meter_no, '') LIKE ?
               OR COALESCE(rp.zone_name, '') LIKE ?
               OR COALESCE(rp.receipt_text, '') LIKE ?
            )""")
        params.extend([like, like, like, like, like, like])
    normalized_month = str(month or "").strip()
    if normalized_month:
        conditions.append("strftime('%Y-%m', COALESCE(r.reading_date, rp.printed_at)) = ?")
        params.append(normalized_month)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY datetime(rp.printed_at) DESC, rp.id DESC"
    if limit is not None:
        normalized_limit = max(1, int(limit))
        sql += " LIMIT ?"
        params.append(normalized_limit)
    rows = conn.execute(sql, tuple(params)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def list_receipt_print_months() -> list[str]:
    """Return every persisted receipt month, newest first."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT DISTINCT strftime('%Y-%m', COALESCE(r.reading_date, rp.printed_at)) AS history_month
        FROM receipt_prints rp
        LEFT JOIN readings r ON r.id = rp.reading_id
        WHERE COALESCE(r.reading_date, rp.printed_at) IS NOT NULL
        ORDER BY history_month DESC
        """
    ).fetchall()
    conn.close()
    return [str(row["history_month"]) for row in rows if row["history_month"]]


def get_receipt_print_by_id(receipt_print_id: int) -> dict | None:
    """Return one saved receipt print row by ID."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT *
        FROM receipt_prints
        WHERE id = ?
        LIMIT 1
        """,
        (receipt_print_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_zone_stats(
    schedule_date: str | None = None,
    meter_reader_id: int | str | None = None,
) -> dict:
    """Return per-zone progress stats: {zone_name: {households, read, flagged}}."""
    conn = get_connection()
    effective_date, effective_reader_id, use_schedule_filter = _effective_schedule_context(schedule_date, meter_reader_id)
    month_start, month_end = _month_bounds(effective_date)
    stats = {}
    if use_schedule_filter:
        zones = conn.execute(
            """
            SELECT DISTINCT z.id, z.name
            FROM zones z
            JOIN reading_schedule rs ON rs.zone_name = z.name
            WHERE rs.meter_reader_id = ?
              AND date(COALESCE(rs.start_date, rs.schedule_date)) <= date(?)
              AND date(COALESCE(rs.due_date, rs.start_date, rs.schedule_date)) >= date(?)
              AND rs.status IN ('Scheduled', 'In Progress')
            ORDER BY rs.zone_name
            """,
            (effective_reader_id, month_end, month_start),
        ).fetchall()
    else:
        zones = conn.execute("SELECT id, name FROM zones ORDER BY name").fetchall()

    for z in zones:
        total = conn.execute(
            "SELECT COUNT(*) FROM consumers WHERE zone_id = ?", (z["id"],)
        ).fetchone()[0]
        if use_schedule_filter:
            read = conn.execute(
                """SELECT COUNT(DISTINCT r.consumer_id)
                   FROM readings r
                   JOIN consumers c ON r.consumer_id = c.id
                   WHERE c.zone_id = ?
                     AND date(r.reading_date) >= date(?)
                     AND date(r.reading_date) <= date(?)""",
                (z["id"], month_start, month_end),
            ).fetchone()[0]
            synced_only_read = conn.execute(
                """SELECT COUNT(*)
                   FROM consumers c
                   WHERE c.zone_id = ?
                     AND c.latest_reading_date IS NOT NULL
                     AND date(c.latest_reading_date) >= date(?)
                     AND date(c.latest_reading_date) <= date(?)
                     AND NOT EXISTS (
                         SELECT 1
                         FROM readings r
                         WHERE r.consumer_id = c.id
                           AND date(r.reading_date) >= date(?)
                           AND date(r.reading_date) <= date(?)
                     )""",
                (z["id"], month_start, month_end, month_start, month_end),
            ).fetchone()[0]
            read += synced_only_read
            flagged = conn.execute(
                """SELECT COUNT(*)
                   FROM readings r
                   JOIN consumers c ON r.consumer_id = c.id
                   WHERE c.zone_id = ?
                     AND date(r.reading_date) >= date(?)
                     AND date(r.reading_date) <= date(?)
                     AND r.is_flagged = 1""",
                (z["id"], month_start, month_end),
            ).fetchone()[0]
        else:
            read = conn.execute(
                """SELECT COUNT(DISTINCT r.consumer_id)
                   FROM readings r
                   JOIN consumers c ON r.consumer_id = c.id
                   WHERE c.zone_id = ?""", (z["id"],)
            ).fetchone()[0]
            flagged = conn.execute(
                """SELECT COUNT(*)
                   FROM readings r
                   JOIN consumers c ON r.consumer_id = c.id
                   WHERE c.zone_id = ? AND r.is_flagged = 1""", (z["id"],)
            ).fetchone()[0]

        stats[z["name"]] = {"households": total, "read": read, "flagged": flagged}

    conn.close()
    return stats


def get_all_zone_names(
    schedule_date: str | None = None,
    meter_reader_id: int | str | None = None,
) -> list[str]:
    """Return a sorted list of zone names."""
    conn = get_connection()
    effective_date, effective_reader_id, use_schedule_filter = _effective_schedule_context(schedule_date, meter_reader_id)
    month_start, month_end = _month_bounds(effective_date)
    if use_schedule_filter:
        rows = conn.execute(
            """
            SELECT DISTINCT rs.zone_name AS name
            FROM reading_schedule rs
            WHERE rs.meter_reader_id = ?
              AND date(COALESCE(rs.start_date, rs.schedule_date)) <= date(?)
              AND date(COALESCE(rs.due_date, rs.start_date, rs.schedule_date)) >= date(?)
              AND rs.status IN ('Scheduled', 'In Progress')
            ORDER BY rs.zone_name
            """,
            (effective_reader_id, month_end, month_start),
        ).fetchall()
    else:
        rows = conn.execute("SELECT name FROM zones ORDER BY name").fetchall()
    conn.close()
    return sorted([r["name"] for r in rows], key=_natural_zone_key)


def get_zone_consumers_with_status(
    zone_name: str,
    schedule_date: str | None = None,
    meter_reader_id: int | str | None = None,
    schedule_id: int | str | None = None,
) -> list[dict]:
    """Return all consumers in a zone with their reading status."""
    conn = get_connection()
    effective_date, effective_reader_id, use_schedule_filter = _effective_schedule_context(schedule_date, meter_reader_id)
    month_start, month_end = _month_bounds(effective_date)
    selected_schedule_id = None
    try:
        selected_schedule_id = int(schedule_id) if schedule_id not in (None, "") else None
    except (TypeError, ValueError):
        selected_schedule_id = None
    if use_schedule_filter and selected_schedule_id is not None:
        sql = """SELECT
            c.id, c.meter_no, COALESCE(ra.acct_no, c.acct_no) AS acct_no,
            c.name, c.address, c.previous_reading,
            c.latest_reading, c.latest_reading_date, c.classification_id, c.classification_name,
            c.minimum_cubic, c.minimum_rate, c.excess_rate_per_cubic, c.due_days,
            c.penalty_percent, c.billing_month, c.date_covered_from, c.date_covered_to,
            c.amount_due, c.previous_balance, c.due_date, c.penalty, c.previous_penalty,
            c.total_after_due_date, c.bill_status, c.late_fee,
            ra.schedule_id, ra.schedule_date, ra.schedule_due_date, ra.billing_cycle,
            ra.assignment_order, ra.reading_route_id,
            ra.zone_name, ra.is_read, ra.reading_status, ra.reading_sync_status,
            r.present_reading AS reading_value, r.consumption, r.reading_date,
            r.exception, r.is_flagged, r.captured_at
        FROM reading_assignment ra
        JOIN consumers c ON c.id = ra.consumer_id
        LEFT JOIN readings r ON r.id = (
            SELECT MAX(r2.id) FROM readings r2
            WHERE r2.consumer_id = ra.consumer_id AND r2.schedule_id = ra.schedule_id
              AND lower(COALESCE(r2.reading_status, 'valid')) NOT IN ('rejected', 'deleted', 'invalid')
        )
        WHERE ra.schedule_id = ? AND ra.zone_name = ?
        """
        params = (selected_schedule_id, zone_name)
    elif use_schedule_filter:
        sql = """SELECT 
            c.id,
            c.meter_no,
            c.acct_no,
            c.name,
            c.address,
            c.previous_reading,
            c.latest_reading,
            c.latest_reading_date,
            c.classification_id,
            c.classification_name,
            c.minimum_cubic,
            c.minimum_rate,
            c.excess_rate_per_cubic,
            c.due_days,
            c.penalty_percent,
            c.billing_month,
            c.date_covered_from,
            c.date_covered_to,
            c.amount_due,
            c.previous_balance,
            c.due_date,
            c.penalty,
            c.previous_penalty,
            c.total_after_due_date,
            c.bill_status,
            c.late_fee,
            CASE
                WHEN r.id IS NOT NULL THEN 1
                WHEN c.latest_reading_date IS NOT NULL
                 AND date(c.latest_reading_date) >= date(?)
                 AND date(c.latest_reading_date) <= date(?)
                THEN 1
                ELSE 0
            END as is_read,
            COALESCE(
                r.present_reading,
                CASE
                    WHEN c.latest_reading_date IS NOT NULL
                     AND date(c.latest_reading_date) >= date(?)
                     AND date(c.latest_reading_date) <= date(?)
                    THEN c.latest_reading
                END
            ) as reading_value,
            r.consumption,
            COALESCE(r.reading_date, c.latest_reading_date) as reading_date,
            r.exception,
            r.is_flagged
           FROM consumers c
           JOIN zones z ON c.zone_id = z.id
           LEFT JOIN (
               SELECT * FROM readings
               WHERE id IN (
                   SELECT MAX(id) FROM readings
                   WHERE date(reading_date) >= date(?)
                     AND date(reading_date) <= date(?)
                   GROUP BY consumer_id
               )
           ) r ON c.id = r.consumer_id
           WHERE z.name = ?
             AND EXISTS (
                 SELECT 1
                 FROM reading_schedule rs
                 WHERE rs.zone_name = z.name
                   AND rs.meter_reader_id = ?
                   AND date(COALESCE(rs.start_date, rs.schedule_date)) <= date(?)
                   AND date(COALESCE(rs.due_date, rs.start_date, rs.schedule_date)) >= date(?)
                   AND rs.status IN ('Scheduled', 'In Progress')
             )
           ORDER BY c.meter_no"""
        params = (
            month_start, month_end,
            month_start, month_end,
            month_start, month_end,
            zone_name, effective_reader_id, month_end, month_start,
        )
    else:
        sql = """SELECT 
            c.id,
            c.meter_no,
            c.acct_no,
            c.name,
            c.address,
            c.previous_reading,
            c.latest_reading,
            c.latest_reading_date,
            c.classification_id,
            c.classification_name,
            c.minimum_cubic,
            c.minimum_rate,
            c.excess_rate_per_cubic,
            c.due_days,
            c.penalty_percent,
            c.billing_month,
            c.date_covered_from,
            c.date_covered_to,
            c.amount_due,
            c.previous_balance,
            c.due_date,
            c.penalty,
            c.previous_penalty,
            c.total_after_due_date,
            c.bill_status,
            c.late_fee,
            CASE
                WHEN r.id IS NOT NULL THEN 1
                WHEN c.latest_reading_date IS NOT NULL THEN 1
                ELSE 0
            END as is_read,
            COALESCE(r.present_reading, c.latest_reading) as reading_value,
            r.consumption,
            COALESCE(r.reading_date, c.latest_reading_date) as reading_date,
            r.exception,
            r.is_flagged
           FROM consumers c
           JOIN zones z ON c.zone_id = z.id
           LEFT JOIN (
               SELECT * FROM readings 
               WHERE id IN (
                   SELECT MAX(id) FROM readings GROUP BY consumer_id
               )
           ) r ON c.id = r.consumer_id
           WHERE z.name = ?
           ORDER BY c.meter_no"""
        params = (zone_name,)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    results = [dict(r) for r in rows]
    today = date.today()
    for item in results:
        due = _normalize_schedule_date(item.get("schedule_due_date") or item.get("due_date"))
        scheduled = _normalize_schedule_date(item.get("schedule_date"))
        item["schedule_date"] = scheduled
        item["schedule_due_date"] = due
        if item.get("is_read"):
            item["deadline_status"] = "Completed"
            item["deadline_days"] = None
            continue
        try:
            delta = (date.fromisoformat(due) - today).days if due else None
        except ValueError:
            delta = None
        item["deadline_days"] = delta
        if delta is None or delta > 2:
            item["deadline_status"] = "Pending"
        elif delta == 2:
            item["deadline_status"] = "Due in 2d"
        elif delta == 1:
            item["deadline_status"] = "Due in 1d"
        elif delta == 0:
            item["deadline_status"] = "Due today"
        else:
            overdue_days = abs(delta)
            item["deadline_status"] = f"Overdue {overdue_days}d"
    return sort_and_mark_nearby(results)


def replace_consumers_from_sync(consumers: list[dict]) -> int:
    """
    Mirror consumer records from the backend API/cache into local SQLite.
    Returns number of consumer rows upserted.
    """
    if not consumers:
        return 0

    conn = get_connection()
    cur = conn.cursor()

    def _real_meter_no(consumer: dict) -> str:
        meter_no = str(consumer.get("meter_no") or "").strip()
        if meter_no and not meter_no.startswith("ACCT-") and not meter_no.startswith("CID-"):
            return meter_no
        return ""

    def _optional_int(value):
        value = _sqlite_safe(value)
        if value is None or value == "":
            return None
        return int(float(value))

    def _optional_float(value):
        value = _sqlite_safe(value)
        if value is None or value == "":
            return None
        return float(value)

    zone_names = sorted(
        {
            (c.get("zone_name") or "Unassigned").strip()
            for c in consumers
            if _real_meter_no(c)
        }
    )
    for zone_name in zone_names:
        cur.execute("INSERT OR IGNORE INTO zones (name) VALUES (?)", (zone_name,))

    zone_rows = cur.execute("SELECT id, name FROM zones").fetchall()
    zone_id_by_name = {row["name"]: row["id"] for row in zone_rows}
    latest_local_readings = {
        row["consumer_id"]: row["present_reading"]
        for row in cur.execute(
            """
            SELECT r.consumer_id, r.present_reading
            FROM readings r
            JOIN (
                SELECT consumer_id, MAX(id) AS latest_id
                FROM readings
                GROUP BY consumer_id
            ) latest
              ON latest.consumer_id = r.consumer_id
             AND latest.latest_id = r.id
            """
        ).fetchall()
    }

    upserted = 0
    for c in consumers:
        c = {key: _sqlite_safe(value) for key, value in c.items()}
        meter_no = _real_meter_no(c)
        if not meter_no:
            continue
        zone_name = (c.get("zone_name") or "Unassigned").strip()
        zone_id = zone_id_by_name.get(zone_name)
        if zone_id is None:
            continue

        # Account numbers are identifiers, not numbers. Preserve every segment
        # exactly as supplied by the assignment service (for example A1 or 0).
        acct_no = str(c.get("acct_no") or "").strip()
        name = _clean_display_name(c.get("name")) or "Unknown"
        address = (str(c.get("address")).strip() if c.get("address") not in (None, "") else None)
        previous_reading = int(c.get("previous_reading") or 0)
        try:
            local_previous = latest_local_readings.get(int(c.get("id")))
        except (TypeError, ValueError):
            local_previous = None
        if local_previous is not None:
            previous_reading = max(previous_reading, int(local_previous or 0))
        classification_id = _optional_int(c.get("classification_id"))
        classification_name = (c.get("classification_name") or "").strip() or None
        minimum_cubic = _optional_int(c.get("minimum_cubic"))
        minimum_rate = _optional_float(c.get("minimum_rate"))
        excess_rate_per_cubic = _optional_float(c.get("excess_rate_per_cubic"))
        due_days = _optional_int(c.get("due_days"))
        penalty_percent = _optional_float(c.get("penalty_percent"))
        billing_month = (str(c.get("billing_month")).strip() if c.get("billing_month") not in (None, "") else None)
        date_covered_from = (str(c.get("date_covered_from")).strip() if c.get("date_covered_from") not in (None, "") else None)
        date_covered_to = (str(c.get("date_covered_to")).strip() if c.get("date_covered_to") not in (None, "") else None)
        amount_due = _optional_float(c.get("amount_due"))
        previous_balance = _optional_float(c.get("previous_balance"))
        due_date = (str(c.get("due_date")).strip() if c.get("due_date") not in (None, "") else None)
        penalty = _optional_float(c.get("penalty"))
        previous_penalty = _optional_float(c.get("previous_penalty"))
        total_after_due_date = _optional_float(c.get("total_after_due_date"))
        bill_status = (str(c.get("bill_status")).strip() if c.get("bill_status") not in (None, "") else None)
        late_fee = _optional_float(c.get("late_fee"))
        latest_reading = _optional_float(c.get("latest_reading"))
        latest_reading_date = (str(c.get("latest_reading_date") or c.get("latest_reading_updated_at")).strip() if c.get("latest_reading_date") not in (None, "") or c.get("latest_reading_updated_at") not in (None, "") else None)
        cid = c.get("id") or c.get("consumer_id")

        local_consumer_id = None
        if cid is not None:
            local_consumer_id = int(cid)
            cur.execute(
                """
                INSERT INTO consumers (
                    id, meter_no, acct_no, name, address, previous_reading, classification_id,
                    classification_name, minimum_cubic, minimum_rate, excess_rate_per_cubic,
                    due_days, penalty_percent, billing_month, date_covered_from, date_covered_to,
                    amount_due, previous_balance, due_date, penalty,
                    previous_penalty, total_after_due_date, bill_status, late_fee, latest_reading, latest_reading_date, zone_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    meter_no = excluded.meter_no,
                    acct_no = excluded.acct_no,
                    name = COALESCE(NULLIF(NULLIF(NULLIF(TRIM(excluded.name), ''), 'Unknown'), 'unknown'), consumers.name),
                    address = COALESCE(NULLIF(TRIM(excluded.address), ''), consumers.address),
                    previous_reading = excluded.previous_reading,
                    classification_id = excluded.classification_id,
                    classification_name = excluded.classification_name,
                    minimum_cubic = excluded.minimum_cubic,
                    minimum_rate = excluded.minimum_rate,
                    excess_rate_per_cubic = excluded.excess_rate_per_cubic,
                    due_days = excluded.due_days,
                    penalty_percent = excluded.penalty_percent,
                    billing_month = COALESCE(NULLIF(TRIM(excluded.billing_month), ''), consumers.billing_month),
                    date_covered_from = COALESCE(NULLIF(TRIM(excluded.date_covered_from), ''), consumers.date_covered_from),
                    date_covered_to = COALESCE(NULLIF(TRIM(excluded.date_covered_to), ''), consumers.date_covered_to),
                    amount_due = excluded.amount_due,
                    previous_balance = excluded.previous_balance,
                    due_date = COALESCE(NULLIF(TRIM(excluded.due_date), ''), consumers.due_date),
                    penalty = excluded.penalty,
                    previous_penalty = excluded.previous_penalty,
                    total_after_due_date = excluded.total_after_due_date,
                    bill_status = excluded.bill_status,
                    late_fee = excluded.late_fee,
                    latest_reading = excluded.latest_reading,
                    latest_reading_date = excluded.latest_reading_date,
                    zone_id = excluded.zone_id
                """,
                (
                    int(cid), meter_no, acct_no, name, address, previous_reading, classification_id,
                    classification_name, minimum_cubic, minimum_rate, excess_rate_per_cubic,
                    due_days, penalty_percent, billing_month, date_covered_from, date_covered_to,
                    amount_due, previous_balance, due_date, penalty,
                    previous_penalty, total_after_due_date, bill_status, late_fee, latest_reading, latest_reading_date, zone_id,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO consumers (
                    meter_no, acct_no, name, address, previous_reading, classification_id,
                    classification_name, minimum_cubic, minimum_rate, excess_rate_per_cubic,
                    due_days, penalty_percent, billing_month, date_covered_from, date_covered_to,
                    amount_due, previous_balance, due_date, penalty,
                    previous_penalty, total_after_due_date, bill_status, late_fee, latest_reading, latest_reading_date, zone_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(meter_no) DO UPDATE SET
                    acct_no = excluded.acct_no,
                    name = COALESCE(NULLIF(NULLIF(NULLIF(TRIM(excluded.name), ''), 'Unknown'), 'unknown'), consumers.name),
                    address = COALESCE(NULLIF(TRIM(excluded.address), ''), consumers.address),
                    previous_reading = excluded.previous_reading,
                    classification_id = excluded.classification_id,
                    classification_name = excluded.classification_name,
                    minimum_cubic = excluded.minimum_cubic,
                    minimum_rate = excluded.minimum_rate,
                    excess_rate_per_cubic = excluded.excess_rate_per_cubic,
                    due_days = excluded.due_days,
                    penalty_percent = excluded.penalty_percent,
                    billing_month = COALESCE(NULLIF(TRIM(excluded.billing_month), ''), consumers.billing_month),
                    date_covered_from = COALESCE(NULLIF(TRIM(excluded.date_covered_from), ''), consumers.date_covered_from),
                    date_covered_to = COALESCE(NULLIF(TRIM(excluded.date_covered_to), ''), consumers.date_covered_to),
                    amount_due = excluded.amount_due,
                    previous_balance = excluded.previous_balance,
                    due_date = COALESCE(NULLIF(TRIM(excluded.due_date), ''), consumers.due_date),
                    penalty = excluded.penalty,
                    previous_penalty = excluded.previous_penalty,
                    total_after_due_date = excluded.total_after_due_date,
                    bill_status = excluded.bill_status,
                    late_fee = excluded.late_fee,
                    latest_reading = excluded.latest_reading,
                    latest_reading_date = excluded.latest_reading_date,
                    zone_id = excluded.zone_id
                """,
                (
                    meter_no, acct_no, name, address, previous_reading, classification_id,
                    classification_name, minimum_cubic, minimum_rate, excess_rate_per_cubic,
                    due_days, penalty_percent, billing_month, date_covered_from, date_covered_to,
                    amount_due, previous_balance, due_date, penalty,
                    previous_penalty, total_after_due_date, bill_status, late_fee, latest_reading, latest_reading_date, zone_id,
                ),
            )
            local_row = cur.execute("SELECT id FROM consumers WHERE meter_no = ?", (meter_no,)).fetchone()
            local_consumer_id = int(local_row["id"]) if local_row else local_consumer_id

        if local_consumer_id is not None and latest_reading is not None and latest_reading_date:
            existing_reading = cur.execute(
                """
                SELECT id FROM readings
                WHERE consumer_id = ?
                  AND date(reading_date) = date(?)
                  AND present_reading = ?
                LIMIT 1
                """,
                (local_consumer_id, latest_reading_date, int(round(float(latest_reading)))),
            ).fetchone()
            if existing_reading is None:
                prior_reading = latest_local_readings.get(local_consumer_id)
                if prior_reading is None or float(prior_reading) == float(latest_reading):
                    prior_reading = previous_reading
                consumption = max(0, int(round(float(latest_reading) - float(prior_reading or 0))))
                cur.execute(
                    """
                    INSERT INTO readings (consumer_id, present_reading, consumption, exception, is_flagged, reading_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (local_consumer_id, int(round(float(latest_reading))), consumption, "Synced", 0, latest_reading_date),
                )
                latest_local_readings[local_consumer_id] = latest_reading

        if local_consumer_id is not None:
            raw_schedule_id = c.get("schedule_id", c.get("Schedule_ID"))
            schedule_row = None
            if raw_schedule_id not in (None, ""):
                try:
                    schedule_row = cur.execute(
                        """
                        SELECT schedule_id, COALESCE(start_date, schedule_date) AS schedule_date,
                               COALESCE(due_date, start_date, schedule_date) AS schedule_due_date,
                               billing_month, zone_name
                        FROM reading_schedule WHERE schedule_id = ? LIMIT 1
                        """,
                        (int(raw_schedule_id),),
                    ).fetchone()
                except (TypeError, ValueError):
                    schedule_row = None
            if schedule_row is None:
                candidates = cur.execute(
                    """
                    SELECT schedule_id, COALESCE(start_date, schedule_date) AS schedule_date,
                           COALESCE(due_date, start_date, schedule_date) AS schedule_due_date,
                           billing_month, zone_name
                    FROM reading_schedule
                    WHERE zone_name = ? AND lower(status) NOT IN ('cancelled')
                    ORDER BY date(COALESCE(start_date, schedule_date)) DESC
                    """,
                    (zone_name,),
                ).fetchall()
                if len(candidates) == 1:
                    schedule_row = candidates[0]
                elif billing_month:
                    matching = [row for row in candidates if str(row["billing_month"] or "") == billing_month]
                    if len(matching) == 1:
                        schedule_row = matching[0]
            if schedule_row is not None:
                raw_assignment_order = c.get("assignment_order", c.get("Assignment_Order"))
                try:
                    assignment_order = int(float(raw_assignment_order)) if raw_assignment_order not in (None, "") else None
                except (TypeError, ValueError):
                    assignment_order = None
                reading_route_id = c.get("reading_route_id", c.get("Reading_Route_ID"))
                reading_route_id = str(reading_route_id) if reading_route_id not in (None, "") else None
                remote_status = str(c.get("reading_status") or "").strip().lower()
                raw_is_read = c.get("is_read")
                remote_is_read = str(raw_is_read).strip().lower() in {"1", "true", "yes"}
                remote_is_read = remote_is_read and remote_status not in {"rejected", "deleted", "invalid"}
                assignment_status = "valid" if remote_is_read else (remote_status or "pending")
                remote_sync = str(c.get("reading_sync_status") or ("synced" if remote_is_read else "pending")).strip().lower()
                cur.execute(
                    """
                    INSERT INTO reading_assignment (
                        schedule_id, consumer_id, schedule_date, schedule_due_date,
                        billing_cycle, zone_name, acct_no, assignment_order, reading_route_id,
                        is_read, reading_status, reading_sync_status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(schedule_id, consumer_id) DO UPDATE SET
                        schedule_date = excluded.schedule_date,
                        schedule_due_date = excluded.schedule_due_date,
                        billing_cycle = excluded.billing_cycle,
                        zone_name = excluded.zone_name,
                        acct_no = excluded.acct_no,
                        assignment_order = excluded.assignment_order,
                        reading_route_id = excluded.reading_route_id,
                        is_read = CASE
                            WHEN reading_assignment.reading_sync_status IN ('pending', 'failed')
                             AND reading_assignment.reading_status = 'valid' THEN 1
                            ELSE excluded.is_read
                        END,
                        reading_status = CASE
                            WHEN reading_assignment.reading_sync_status IN ('pending', 'failed')
                             AND reading_assignment.reading_status = 'valid' THEN reading_assignment.reading_status
                            ELSE excluded.reading_status
                        END,
                        reading_sync_status = CASE
                            WHEN reading_assignment.reading_sync_status IN ('pending', 'failed')
                             AND reading_assignment.reading_status = 'valid' THEN reading_assignment.reading_sync_status
                            ELSE excluded.reading_sync_status
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        schedule_row["schedule_id"], local_consumer_id, schedule_row["schedule_date"],
                        schedule_row["schedule_due_date"],
                        c.get("billing_cycle") or schedule_row["billing_month"], schedule_row["zone_name"],
                        acct_no, assignment_order, reading_route_id,
                        1 if remote_is_read else 0, assignment_status, remote_sync,
                    ),
                )
        upserted += 1

    conn.commit()
    conn.close()
    return upserted

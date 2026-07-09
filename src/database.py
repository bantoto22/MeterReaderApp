"""
database.py – SQLite helper for the Water Meter Reader application.
Uses Python's built-in sqlite3 module (no extra install needed).
"""

import os
import sqlite3
from decimal import Decimal

sqlite3.register_adapter(Decimal, float)

DB_NAME = "meter.db"


def _db_path():
    """Return the absolute path to the database file in the data folder."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", DB_NAME)


def get_connection():
    """Return a new connection to the database with foreign keys enabled."""
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row          # allows dict-like access on rows
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _sqlite_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _ensure_columns(conn: sqlite3.Connection, table_name: str, column_defs: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for name, definition in column_defs.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")


# ─── Schema creation ─────────────────────────────────────────────────────────
def init_db():
    """Create the tables if they don't exist and seed only local user accounts."""
    conn = get_connection()
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
            previous_reading INTEGER NOT NULL DEFAULT 0,
            classification_id INTEGER,
            classification_name TEXT,
            minimum_cubic INTEGER,
            minimum_rate REAL,
            excess_rate_per_cubic REAL,
            due_days INTEGER,
            penalty_percent REAL,
            amount_due REAL,
            previous_balance REAL,
            due_date TEXT,
            penalty REAL,
            previous_penalty REAL,
            total_after_due_date REAL,
            bill_status TEXT,
            late_fee REAL,
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
    """)

    _ensure_columns(
        conn,
        "consumers",
        {
            "classification_id": "INTEGER",
            "classification_name": "TEXT",
            "minimum_cubic": "INTEGER",
            "minimum_rate": "REAL",
            "excess_rate_per_cubic": "REAL",
            "due_days": "INTEGER",
            "penalty_percent": "REAL",
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

    # Seed default users if table is empty (separate from zones check)
    if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        users = [
            ("reader1", "pass123", "Juan Santos", "MR-001"),
            ("reader2", "pass456", "Maria Cruz", "MR-002"),
        ]
        cur.executemany(
            "INSERT INTO users (username, password, name, reader_id) VALUES (?, ?, ?, ?)",
            users
        )

    conn.commit()
    conn.close()


def seed_default_users():
    """Seed default users if users table is empty. Call this to fix empty user table."""
    conn = get_connection()
    cur = conn.cursor()
    
    if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        users = [
            ("reader1", "pass123", "Juan Santos", "MR-001"),
            ("reader2", "pass456", "Maria Cruz", "MR-002"),
        ]
        cur.executemany(
            "INSERT INTO users (username, password, name, reader_id) VALUES (?, ?, ?, ?)",
            users
        )
        conn.commit()
    conn.close()


def authenticate_user(username: str, password: str) -> dict | None:
    """Validate user credentials. Returns user dict or None if invalid."""
    conn = get_connection()
    row = conn.execute(
        "SELECT username, password, name, reader_id FROM users WHERE username = ?",
        (username,)
    ).fetchone()
    conn.close()
    
    if row and row['password'] == password:
        return {
            'username': row['username'],
            'name': row['name'],
            'id': row['reader_id']
        }
    return None


def get_all_users() -> list[dict]:
    """Return all users for login hint display."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT username, name, reader_id FROM users ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Query helpers ────────────────────────────────────────────────────────────

def search_consumer(meter_no: str, unread_only: bool = True) -> dict | None:
    """Look up a consumer by meter/account/name. Returns dict or None."""
    conn = get_connection()
    normalized = "".join(ch for ch in str(meter_no or "") if ch.isalnum())
    if unread_only:
        sql = """SELECT c.id, c.meter_no, c.acct_no, c.name, c.previous_reading,
                        c.classification_id, c.classification_name, c.minimum_cubic,
                        c.minimum_rate, c.excess_rate_per_cubic, c.due_days, c.penalty_percent,
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
                 )
                   AND NOT EXISTS (
                       SELECT 1 FROM readings r WHERE r.consumer_id = c.id
                   )
                 ORDER BY CASE
                     WHEN c.meter_no = ? THEN 0
                     WHEN c.acct_no = ? THEN 1
                     WHEN c.name = ? THEN 2
                     WHEN REPLACE(REPLACE(c.meter_no, '-', ''), ' ', '') = ? THEN 3
                     WHEN REPLACE(REPLACE(c.acct_no, '-', ''), ' ', '') = ? THEN 4
                     ELSE 5
                 END
                 LIMIT 1"""
    else:
        sql = """SELECT c.id, c.meter_no, c.acct_no, c.name, c.previous_reading,
                        c.classification_id, c.classification_name, c.minimum_cubic,
                        c.minimum_rate, c.excess_rate_per_cubic, c.due_days, c.penalty_percent,
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
                 )
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
        meter_no, meter_no, meter_no, normalized, normalized,
        meter_no, meter_no, meter_no, normalized, normalized,
    )
    row = conn.execute(sql, params).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None



def search_consumers_by_zone(query: str, zone_name: str, limit: int = 8, unread_only: bool = True) -> list[dict]:
    """Search consumers by partial meter_no or name, filtered to a specific zone."""
    conn = get_connection()
    like_pattern = f"%{query}%"
    normalized = "".join(ch for ch in str(query or "") if ch.isalnum())
    normalized_like = f"%{normalized}%"
    if unread_only:
        sql = """SELECT c.id, c.meter_no, c.acct_no, c.name, c.previous_reading,
                        c.classification_id, c.classification_name, c.minimum_cubic,
                        c.minimum_rate, c.excess_rate_per_cubic, c.due_days, c.penalty_percent,
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
                   )
                   AND NOT EXISTS (
                       SELECT 1 FROM readings r WHERE r.consumer_id = c.id
                   )
                 ORDER BY c.meter_no
                 LIMIT ?"""
    else:
        sql = """SELECT c.id, c.meter_no, c.acct_no, c.name, c.previous_reading,
                        c.classification_id, c.classification_name, c.minimum_cubic,
                        c.minimum_rate, c.excess_rate_per_cubic, c.due_days, c.penalty_percent,
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
                   )
                 ORDER BY c.meter_no
                 LIMIT ?"""
    rows = conn.execute(
        sql,
        (zone_name, like_pattern, like_pattern, like_pattern, normalized_like, normalized_like, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_reading(
    consumer_id: int,
    present_reading: float,
    consumption: float,
    exception: str = "None",
    is_flagged: bool = False,
    reading_date: str | None = None,
):
    """Insert a new reading record and update the consumer's previous reading."""
    conn = get_connection()
    cur = conn.cursor()
    if reading_date:
        cur.execute(
            "INSERT INTO readings (consumer_id, present_reading, consumption, exception, is_flagged, reading_date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (consumer_id, present_reading, consumption, exception, 1 if is_flagged else 0, reading_date),
        )
    else:
        cur.execute(
            "INSERT INTO readings (consumer_id, present_reading, consumption, exception, is_flagged) "
            "VALUES (?, ?, ?, ?, ?)",
            (consumer_id, present_reading, consumption, exception, 1 if is_flagged else 0),
        )
    conn.execute(
        "UPDATE consumers SET previous_reading = ? WHERE id = ?",
        (present_reading, consumer_id))
    conn.commit()
    reading_id = cur.lastrowid
    conn.close()
    return reading_id


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
            acct_no,
            consumer_name or "Unknown",
            meter_no or "N/A",
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


def list_receipt_print_history(search_text: str = "", limit: int = 200) -> list[dict]:
    """Return recent receipt print history rows for preview and reprint."""
    conn = get_connection()
    normalized_limit = max(1, min(int(limit or 200), 500))
    sql = """
        SELECT
            rp.*,
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
    """
    params: list[object] = []
    trimmed = (search_text or "").strip()
    if trimmed:
        like = f"%{trimmed}%"
        sql += """
            WHERE CAST(rp.id AS TEXT) LIKE ?
               OR COALESCE(rp.acct_no, '') LIKE ?
               OR COALESCE(rp.consumer_name, '') LIKE ?
               OR COALESCE(rp.meter_no, '') LIKE ?
               OR COALESCE(rp.zone_name, '') LIKE ?
               OR COALESCE(rp.receipt_text, '') LIKE ?
        """
        params.extend([like, like, like, like, like, like])
    sql += " ORDER BY rp.printed_at DESC, rp.id DESC LIMIT ?"
    params.append(normalized_limit)
    rows = conn.execute(sql, tuple(params)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


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


def get_zone_stats() -> dict:
    """Return per-zone progress stats: {zone_name: {households, read, flagged}}."""
    conn = get_connection()

    stats = {}
    zones = conn.execute("SELECT id, name FROM zones ORDER BY name").fetchall()

    for z in zones:
        total = conn.execute(
            "SELECT COUNT(*) FROM consumers WHERE zone_id = ?", (z["id"],)
        ).fetchone()[0]

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


def get_all_zone_names() -> list[str]:
    """Return a sorted list of zone names."""
    conn = get_connection()
    rows = conn.execute("SELECT name FROM zones ORDER BY name").fetchall()
    conn.close()
    return [r["name"] for r in rows]


def get_zone_consumers_with_status(zone_name: str) -> list[dict]:
    """Return all consumers in a zone with their reading status."""
    conn = get_connection()
    
    rows = conn.execute(
        """SELECT 
            c.id,
            c.meter_no,
            c.acct_no,
            c.name,
            c.previous_reading,
            c.classification_id,
            c.classification_name,
            c.minimum_cubic,
            c.minimum_rate,
            c.excess_rate_per_cubic,
            c.due_days,
            c.penalty_percent,
            c.amount_due,
            c.previous_balance,
            c.due_date,
            c.penalty,
            c.previous_penalty,
            c.total_after_due_date,
            c.bill_status,
            c.late_fee,
            CASE WHEN r.id IS NOT NULL THEN 1 ELSE 0 END as is_read,
            r.present_reading as reading_value,
            r.consumption,
            r.reading_date,
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
           ORDER BY c.meter_no""",
        (zone_name,)
    ).fetchall()
    
    conn.close()
    return [dict(r) for r in rows]


def replace_consumers_from_sync(consumers: list[dict]) -> int:
    """
    Mirror consumer records from sync source (Supabase/cache) into local SQLite.
    Returns number of consumer rows upserted.
    """
    if not consumers:
        return 0

    conn = get_connection()
    cur = conn.cursor()

    def _is_fallback_meter_no(value: str | None) -> bool:
        text = str(value or "").strip()
        return text.startswith("ACCT-") or text.startswith("CID-")

    def _real_meter_no(consumer: dict) -> str:
        meter_no = str(consumer.get("meter_no") or "").strip()
        if meter_no and not _is_fallback_meter_no(meter_no):
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

        acct_no = (c.get("acct_no") or "").strip()
        name = (c.get("name") or "Unknown").strip()
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
        amount_due = _optional_float(c.get("amount_due"))
        previous_balance = _optional_float(c.get("previous_balance"))
        due_date = (str(c.get("due_date")).strip() if c.get("due_date") not in (None, "") else None)
        penalty = _optional_float(c.get("penalty"))
        previous_penalty = _optional_float(c.get("previous_penalty"))
        total_after_due_date = _optional_float(c.get("total_after_due_date"))
        bill_status = (str(c.get("bill_status")).strip() if c.get("bill_status") not in (None, "") else None)
        late_fee = _optional_float(c.get("late_fee"))
        cid = c.get("id")

        if cid is not None:
            cur.execute(
                """
                INSERT INTO consumers (
                    id, meter_no, acct_no, name, previous_reading, classification_id,
                    classification_name, minimum_cubic, minimum_rate, excess_rate_per_cubic,
                    due_days, penalty_percent, amount_due, previous_balance, due_date, penalty,
                    previous_penalty, total_after_due_date, bill_status, late_fee, zone_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    meter_no = excluded.meter_no,
                    acct_no = excluded.acct_no,
                    name = excluded.name,
                    previous_reading = excluded.previous_reading,
                    classification_id = excluded.classification_id,
                    classification_name = excluded.classification_name,
                    minimum_cubic = excluded.minimum_cubic,
                    minimum_rate = excluded.minimum_rate,
                    excess_rate_per_cubic = excluded.excess_rate_per_cubic,
                    due_days = excluded.due_days,
                    penalty_percent = excluded.penalty_percent,
                    amount_due = excluded.amount_due,
                    previous_balance = excluded.previous_balance,
                    due_date = excluded.due_date,
                    penalty = excluded.penalty,
                    previous_penalty = excluded.previous_penalty,
                    total_after_due_date = excluded.total_after_due_date,
                    bill_status = excluded.bill_status,
                    late_fee = excluded.late_fee,
                    zone_id = excluded.zone_id
                """,
                (
                    int(cid), meter_no, acct_no, name, previous_reading, classification_id,
                    classification_name, minimum_cubic, minimum_rate, excess_rate_per_cubic,
                    due_days, penalty_percent, amount_due, previous_balance, due_date, penalty,
                    previous_penalty, total_after_due_date, bill_status, late_fee, zone_id,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO consumers (
                    meter_no, acct_no, name, previous_reading, classification_id,
                    classification_name, minimum_cubic, minimum_rate, excess_rate_per_cubic,
                    due_days, penalty_percent, amount_due, previous_balance, due_date, penalty,
                    previous_penalty, total_after_due_date, bill_status, late_fee, zone_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(meter_no) DO UPDATE SET
                    acct_no = excluded.acct_no,
                    name = excluded.name,
                    previous_reading = excluded.previous_reading,
                    classification_id = excluded.classification_id,
                    classification_name = excluded.classification_name,
                    minimum_cubic = excluded.minimum_cubic,
                    minimum_rate = excluded.minimum_rate,
                    excess_rate_per_cubic = excluded.excess_rate_per_cubic,
                    due_days = excluded.due_days,
                    penalty_percent = excluded.penalty_percent,
                    amount_due = excluded.amount_due,
                    previous_balance = excluded.previous_balance,
                    due_date = excluded.due_date,
                    penalty = excluded.penalty,
                    previous_penalty = excluded.previous_penalty,
                    total_after_due_date = excluded.total_after_due_date,
                    bill_status = excluded.bill_status,
                    late_fee = excluded.late_fee,
                    zone_id = excluded.zone_id
                """,
                (
                    meter_no, acct_no, name, previous_reading, classification_id,
                    classification_name, minimum_cubic, minimum_rate, excess_rate_per_cubic,
                    due_days, penalty_percent, amount_due, previous_balance, due_date, penalty,
                    previous_penalty, total_after_due_date, bill_status, late_fee, zone_id,
                ),
            )
        upserted += 1

    conn.commit()
    conn.close()
    return upserted

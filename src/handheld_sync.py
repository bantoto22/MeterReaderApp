"""
Handheld sync layer for online/offline meter reading operations.

Online:
- Reads/writes through the Node backend HTTPS API.

Offline:
- Writes are queued in local SQLite on the Pi.
- Reads use local cached consumers/meters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from urllib import error, parse, request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from .sqlite_support import connect_sqlite
except ImportError:
    from sqlite_support import connect_sqlite

sqlite3.register_adapter(Decimal, float)

BACKGROUND_SYNC_INTERVAL_SECONDS = 300


def _manila_current_date(now: datetime | None = None) -> date:
    try:
        manila = ZoneInfo("Asia/Manila")
    except ZoneInfoNotFoundError:
        manila = timezone(timedelta(hours=8), name="Asia/Manila")
    if now is None:
        return datetime.now(manila).date()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(manila).date()

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


def _update_local_reading_state(reading_id: str | None, sync_status: str, reading_status: str | None = None) -> None:
    """Best-effort bridge from queue outcomes to the schedule-scoped local reading."""
    if not reading_id:
        return
    try:
        try:
            from .database import update_reading_sync_state
        except ImportError:
            from database import update_reading_sync_state
        update_reading_sync_state(str(reading_id), sync_status, reading_status)
    except Exception:
        # Queue persistence remains authoritative; a later refresh can reconcile state.
        return


def format_sync_error(stage: str, exc: Exception | str, endpoint: str = "") -> str:
    """Return an operator-friendly diagnostic without discarding the raw error."""
    detail = str(exc or "Unknown error").strip() or "Unknown error"
    lowered = detail.lower()
    problem = "Unexpected sync error"
    action = "Open Sync Logs and report the full details below."
    if "database is locked" in lowered or "database table is locked" in lowered:
        problem = "The device's local SQLite database is busy"
        action = "Close duplicate device-app instances, restart the app, then run Sync Now once."
    elif any(method in lowered for method in ("cannot get /api/handheld", "cannot post /api/handheld")) or ("404" in lowered and "/api/handheld" in lowered):
        problem = "The running backend does not have the handheld API route"
        action = "Restart the Node backend so the latest /api/handheld routes are loaded."
    elif "timed out" in lowered or "timeout" in lowered:
        problem = "The Backend API request timed out"
        action = "Check internet/Tailscale Funnel connectivity, then retry. The reading remains queued."
    elif any(token in lowered for token in ("urlopen error", "connection refused", "name or service", "unreachable")):
        problem = "The Backend API is unreachable"
        action = "Check device internet, Tailscale Funnel, and that the backend is running on port 3001."
    elif "401" in lowered or "403" in lowered or "unauthorized" in lowered or "forbidden" in lowered:
        problem = "The backend rejected device authentication"
        action = "Log in online again and verify that the meter-reader account is active."
    elif "500" in lowered or "postgres" in lowered:
        problem = "The backend could not complete the PostgreSQL operation"
        action = "Check backend and PostgreSQL logs; the device reading remains queued for retry."

    lines = [f"Stage: {stage}", f"Problem: {problem}"]
    if endpoint:
        lines.append(f"Endpoint: {endpoint}")
    lines.extend((f"Details: {detail}", f"Recommended action: {action}"))
    return "\n".join(lines)


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


def _cached_assignment_sort_key(row: dict) -> tuple:
    """Use backend order first and a segment-aware account order as fallback."""
    raw_order = row.get("assignment_order")
    try:
        order_key = (0, float(raw_order)) if raw_order not in (None, "") else (1, 0.0)
    except (TypeError, ValueError):
        order_key = (1, 0.0)
    account_segments = []
    for segment in str(row.get("acct_no") or "").strip().split("-"):
        account_segments.append(tuple(
            (0, int(token)) if token.isdigit() else (1, token.lower())
            for token in re.findall(r"\d+|[^\d]+", segment)
        ))
    return (*order_key, tuple(account_segments), int(row.get("consumer_id") or row.get("id") or 0))


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


def _flatten_backend_bill_context(payload: dict) -> dict:
    """Expose authoritative nested bill values at the context's top level."""
    context = dict(payload or {})
    wrapped = context.get("data") or context.get("Data")
    if isinstance(wrapped, dict):
        context.update(wrapped)
    consumer = context.get("consumer") or context.get("Consumer")
    if isinstance(consumer, dict):
        context = {**consumer, **context}
    bill = context.get("bill") or context.get("Bill")
    if isinstance(bill, dict):
        context.update(bill)
        context["bill"] = dict(bill)

    aliases = {
        "amount_due": ("Amount_Due",),
        "penalty": ("Penalty", "Penalties"),
        "previous_penalty": ("Previous_Penalty",),
        "total_after_due_date": ("Total_After_Due_Date",),
        "overdue_penalty": ("Overdue_Penalty",),
        "late_fee": ("Late_Fee_Percentage", "Late_Fee"),
        "is_overdue": ("Is_Overdue",),
        "status": ("Status",),
        "due_date": ("Due_Date",),
        "water_charge": ("Water_Charge",),
        "class_cost": ("Class_Cost",),
        "billing_reference": ("Billing_Reference",),
        "sync_id": ("Sync_ID",),
    }
    for canonical, source_names in aliases.items():
        if context.get(canonical) not in (None, ""):
            continue
        for source_name in source_names:
            if context.get(source_name) not in (None, ""):
                context[canonical] = context[source_name]
                break
    if context.get("status") not in (None, ""):
        context["bill_status"] = context["status"]
    return context


def _device_schedule_window(today: date | None = None) -> tuple[str, str]:
    anchor = today or datetime.now().date()
    current_month_start = anchor.replace(day=1)
    start = current_month_start.replace(year=current_month_start.year - 1)
    year = current_month_start.year + ((current_month_start.month) // 12)
    month = 1 if current_month_start.month == 12 else current_month_start.month + 1
    next_month_start = date(year, month, 1)
    following_year = next_month_start.year + ((next_month_start.month) // 12)
    following_month = 1 if next_month_start.month == 12 else next_month_start.month + 1
    following_start = date(following_year, following_month, 1)
    end = following_start - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _compute_charge(consumption: int, minimum_cubic, minimum_rate, excess_rate_per_cubic) -> float:
    safe_consumption = max(consumption, 0)
    minimum_cubic_int = _safe_int(minimum_cubic)
    minimum_rate_val = _safe_float(minimum_rate)
    excess_rate_val = _safe_float(excess_rate_per_cubic)
    if safe_consumption <= minimum_cubic_int:
        return round(minimum_rate_val, 2)
    return round(minimum_rate_val + ((safe_consumption - minimum_cubic_int) * excess_rate_val), 2)


_FEE_ALIASES = {
    "water_meter_fee": ("water_meter_fee", "meter_maintenance_fee", "meter_fee"),
    "connection_fee": ("connection_fee",),
    "membership_fee": ("membership_fee",),
}

_FEE_COMPONENT_CODES = {
    "water_meter_fee": "MTR",
    "connection_fee": "CONN",
    "membership_fee": "MEM",
}


def _component_fee(source: dict, fee_name: str) -> float | None:
    components = source.get("connection_fee_components")
    target_code = _FEE_COMPONENT_CODES[fee_name]
    if isinstance(components, dict):
        value = components.get(target_code, components.get(target_code.lower()))
        if isinstance(value, dict):
            for amount_name in ("amount", "fee_amount", "component_amount", "value"):
                if value.get(amount_name) not in (None, ""):
                    return max(0.0, _safe_float(value.get(amount_name)))
        elif value not in (None, ""):
            return max(0.0, _safe_float(value))
    if isinstance(components, list):
        for component in components:
            if not isinstance(component, dict):
                continue
            code = next(
                (
                    component.get(code_name)
                    for code_name in (
                        "code", "component_code", "fee_code", "fee_type", "component", "type", "component_type"
                    )
                    if component.get(code_name) not in (None, "")
                ),
                "",
            )
            if str(code).strip().upper() != target_code:
                continue
            for amount_name in ("amount", "fee_amount", "component_amount", "value"):
                if component.get(amount_name) not in (None, ""):
                    return max(0.0, _safe_float(component.get(amount_name)))
    return None


def _fee_value(source: dict, fee_name: str) -> float:
    component_value = _component_fee(source, fee_name)
    if component_value is not None:
        return component_value
    sources = [source]
    for container_name in ("fees", "consumer_fees", "concessionaire_fees"):
        nested = source.get(container_name)
        if isinstance(nested, dict):
            sources.append(nested)
    for candidate in sources:
        for field_name in _FEE_ALIASES[fee_name]:
            if candidate.get(field_name) not in (None, ""):
                return max(0.0, _safe_float(candidate.get(field_name)))
    return 0.0


def _first_money(source: dict, field_names: tuple[str, ...]) -> float | None:
    for field_name in field_names:
        if source.get(field_name) not in (None, ""):
            return max(0.0, _safe_float(source.get(field_name)))
    return None


def _unpaid_bill_base_amount(unpaid_bill: dict) -> float:
    explicit = _first_money(unpaid_bill, ("original_amount", "current_month_amount", "monthly_amount"))
    if explicit is not None:
        return explicit

    water_charge = _first_money(unpaid_bill, ("water_charge", "class_cost"))
    if water_charge is not None:
        return round(water_charge + sum(_fee_value(unpaid_bill, name) for name in _FEE_ALIASES), 2)

    amount_due = _first_money(unpaid_bill, ("amount_due", "total_amount", "bill_amount"))
    if amount_due is None:
        return 0.0
    previous_balance = _first_money(unpaid_bill, ("previous_balance",))
    previous_penalty = _first_money(unpaid_bill, ("previous_penalty",))
    if previous_balance is not None or previous_penalty is not None:
        return max(0.0, round(amount_due - (previous_balance or 0.0) - (previous_penalty or 0.0), 2))
    return amount_due


def _stored_bill_penalty(unpaid_bill: dict) -> float:
    stored = _first_money(
        unpaid_bill,
        ("own_penalty", "current_penalty", "penalty", "penalty_amount", "late_penalty", "late_fee_amount"),
    ) or 0.0
    amount_due = _first_money(unpaid_bill, ("amount_due", "total_amount", "bill_amount"))
    total_after_due = _first_money(
        unpaid_bill,
        ("total_after_due_date", "amount_after_due_date", "pay_through"),
    )
    if amount_due is not None and total_after_due is not None:
        stored = max(stored, round(max(0.0, total_after_due - amount_due), 2))
    return stored


def _build_bill_payload(
    reading: dict,
    context: dict,
    remote_reading_id: int,
    *,
    as_of_date: date | None = None,
) -> dict:
    reference_date = _reading_date(reading.get("bill_date") or reading.get("reading_date"))
    penalty_date = as_of_date or _manila_current_date()
    present_reading = _safe_int(reading.get("present_reading"))
    consumption = _safe_int(reading.get("consumption"))
    previous_reading = _safe_int(reading.get("previous_reading"), present_reading - consumption)
    current_charge = _compute_charge(
        consumption,
        context.get("minimum_cubic"),
        context.get("minimum_rate"),
        context.get("excess_rate_per_cubic"),
    )
    water_meter_fee = _fee_value(context, "water_meter_fee")
    connection_fee = _fee_value(context, "connection_fee")
    membership_fee = _fee_value(context, "membership_fee")
    concessionaire_fees = round(water_meter_fee + connection_fee + membership_fee, 2)

    due_days = _safe_int(context.get("due_days"), 15) or 15
    configured_late_fee = context.get("late_fee")
    if configured_late_fee in (None, ""):
        configured_late_fee = context.get("penalty_percent")
    late_fee_percent = max(0.0, _safe_float(configured_late_fee, 10.0))
    carried_balance = 0.0
    carried_penalty = 0.0

    # This is only an offline estimate. A reliable carry-forward requires every
    # unpaid monthly bill; a rolled-up latest bill must never be treated as new
    # principal or have another penalty applied to it.
    unpaid_bills = context.get("unpaid_bills")
    used_itemized_unpaid_bills = False
    if isinstance(unpaid_bills, list):
        current_bill_sync_id = str(reading.get("bill_sync_id") or "").strip()
        for unpaid_bill in unpaid_bills:
            if not isinstance(unpaid_bill, dict):
                continue
            prior_status = str(
                unpaid_bill.get("status")
                or unpaid_bill.get("bill_status")
                or unpaid_bill.get("payment_status")
                or "Unpaid"
            ).strip().lower()
            if prior_status == "paid":
                continue
            unpaid_sync_id = str(unpaid_bill.get("sync_id") or unpaid_bill.get("bill_sync_id") or "").strip()
            if current_bill_sync_id and unpaid_sync_id == current_bill_sync_id:
                continue
            original_amount = _unpaid_bill_base_amount(unpaid_bill)
            own_penalty = _stored_bill_penalty(unpaid_bill)
            unpaid_due_date = _parse_date(
                unpaid_bill.get("due_date") or unpaid_bill.get("payment_due_date")
            )
            if unpaid_due_date is not None and penalty_date > unpaid_due_date:
                prior_fees = sum(_fee_value(unpaid_bill, name) for name in _FEE_ALIASES)
                penalty_base = next(
                    (
                        max(0.0, _safe_float(unpaid_bill.get(field_name)))
                        for field_name in ("water_charge", "class_cost")
                        if unpaid_bill.get(field_name) not in (None, "")
                    ),
                    max(0.0, original_amount - prior_fees),
                )
                bill_late_fee = _first_money(unpaid_bill, ("late_fee", "late_fee_percent", "penalty_percent"))
                effective_late_fee = late_fee_percent if bill_late_fee is None else bill_late_fee
                if penalty_base > 0:
                    own_penalty = round(penalty_base * (effective_late_fee / 100.0), 2)
            elif unpaid_due_date is not None:
                own_penalty = 0.0
            if original_amount > 0 or own_penalty > 0:
                used_itemized_unpaid_bills = True
            carried_balance += original_amount
            carried_penalty += own_penalty
    if not used_itemized_unpaid_bills:
        # Older context responses expose only the latest bill's rolled totals.
        # Carry that aggregate exactly once: amount_due already contains all
        # earlier principal and penalties, while the latest bill's own penalty
        # is the difference to total_after_due_date (or the stored penalty).
        prior_status = str(context.get("bill_status") or context.get("status") or "Unpaid").strip().lower()
        if prior_status != "paid" and context.get("amount_due") not in (None, ""):
            rolled_amount_due = max(0.0, _safe_float(context.get("amount_due")))
            embedded_previous_penalty = max(0.0, _safe_float(context.get("previous_penalty")))
            carried_balance = max(0.0, round(rolled_amount_due - embedded_previous_penalty, 2))
            prior_due_date = _parse_date(context.get("prior_bill_due_date") or context.get("due_date"))
            total_after_due = max(0.0, _safe_float(context.get("total_after_due_date")))
            stored_current_penalty = max(
                max(0.0, round(total_after_due - rolled_amount_due, 2)),
                max(0.0, _safe_float(context.get("current_penalty"))),
                max(0.0, _safe_float(context.get("penalty"))),
            )
            current_penalty = stored_current_penalty
            carried_penalty = round(embedded_previous_penalty + current_penalty, 2)
            if prior_due_date is not None:
                penalty_base = _first_money(context, ("water_charge", "class_cost"))
                if penalty_date > prior_due_date and penalty_base is not None:
                    carried_penalty = round(
                        embedded_previous_penalty + (penalty_base * (late_fee_percent / 100.0)),
                        2,
                    )
                elif penalty_date <= prior_due_date:
                    carried_penalty = embedded_previous_penalty
        elif prior_status != "paid":
            carried_balance = max(0.0, _safe_float(context.get("previous_balance")))
            carried_penalty = max(0.0, _safe_float(context.get("previous_penalty")))

    bill_date = datetime.combine(reference_date, datetime.min.time())
    supplied_due_date = _parse_date(reading.get("due_date") or reading.get("schedule_due_date"))
    due_date_obj = supplied_due_date or (reference_date + timedelta(days=due_days))
    due_date = datetime.combine(due_date_obj, datetime.min.time())
    amount_due = round(current_charge + concessionaire_fees + carried_balance + carried_penalty, 2)
    current_penalty = (
        round(current_charge * (late_fee_percent / 100.0), 2)
        if penalty_date > due_date_obj
        else 0.0
    )
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
        # The backend bill schema calls the water-meter charge
        # meter_maintenance_fee. It is a fee for the meter itself.
        "meter_maintenance_fee": water_meter_fee,
        "connection_fee": connection_fee,
        "membership_fee": membership_fee,
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
    backend_api_base_url: str = ""
    sync_enabled: bool = False
    device_id: str = ""

    @classmethod
    def from_env(cls, fail_fast: bool = False) -> "SyncConfig":
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        env_path = os.path.join(project_root, ".env")
        loaded = load_dotenv(env_path)
        if not loaded:
            _load_env_fallback(env_path)

        sync_enabled = os.getenv("HANDHELD_SYNC_ENABLED", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}
        required = ["BACKEND_API_BASE_URL", "HANDHELD_DEVICE_ID"]

        missing = [k for k in required if not os.getenv(k)]
        if (fail_fast or sync_enabled) and missing:
            raise RuntimeError(
                "Missing required sync environment variables: "
                + ", ".join(missing)
                + ". Update .env from .env.example."
            )

        return cls(
            backend_api_base_url=os.getenv("BACKEND_API_BASE_URL", "").rstrip("/"),
            sync_enabled=sync_enabled,
            device_id=os.getenv("HANDHELD_DEVICE_ID", "").strip(),
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
        backend_status: str = "pending",
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

    def get_or_create_bill_reservation(
        self,
        consumer_id: int,
        bill_date: str,
        reading_sync_id: str | None = None,
    ) -> dict:
        raise NotImplementedError

    def save_reserved_reference(self, bill_sync_id: str, billing_reference: str) -> None:
        raise NotImplementedError

    def mark_bill_reservation_used(self, bill_sync_id: str, bill_id: int | str | None = None) -> None:
        raise NotImplementedError


class SQLiteLocalSyncStore(LocalSyncStore):
    def __init__(self, cfg: SyncConfig):
        self._db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "meter.db"))

    def _connect(self):
        return connect_sqlite(self._db_path)

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
            _safe_int(row.get("id") or row.get("consumer_id"), None),
            meter_no,
            str(row.get("acct_no") or ""),
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
            _fee_value(row, "water_meter_fee"),
            _fee_value(row, "connection_fee"),
            _fee_value(row, "membership_fee"),
            _safe_float(row.get("previous_reading"), 0.0),
        )

    def _ensure_columns(self, conn: sqlite3.Connection, table_name: str, column_defs: dict[str, str]) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        for name, definition in column_defs.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")

    @staticmethod
    def _combined_status(backend_status: str) -> str:
        state = str(backend_status or "pending").lower()
        return state if state in {"pending", "failed", "conflict", "synced"} else "pending"

    def _refresh_queue_status(self, conn: sqlite3.Connection, queue_id: int) -> None:
        row = conn.execute(
            """
            SELECT backend_status, backend_synced_at
            FROM sync_queue_meter_readings
            WHERE id = ?
            """,
            (queue_id,),
        ).fetchone()
        if not row:
            return
        status = self._combined_status(row["backend_status"])
        synced_at = None
        if status == "synced":
            synced_at = row["backend_synced_at"] or datetime.now().isoformat()
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
            backend_status TEXT NOT NULL DEFAULT 'pending',
            retries INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            conflict_reason TEXT,
            server_payload TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            synced_at TEXT,
            backend_synced_at TEXT
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
            water_meter_fee REAL NOT NULL DEFAULT 0,
            connection_fee REAL NOT NULL DEFAULT 0,
            membership_fee REAL NOT NULL DEFAULT 0,
            previous_reading INTEGER,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS local_billing_reference_reservations (
            bill_sync_id TEXT PRIMARY KEY,
            reading_sync_id TEXT NOT NULL,
            consumer_id INTEGER NOT NULL,
            schedule_id INTEGER,
            billing_cycle TEXT,
            bill_date TEXT NOT NULL,
            due_date TEXT,
            late_fee REAL,
            billing_reference TEXT,
            status TEXT NOT NULL DEFAULT 'Pending',
            bill_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            used_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_local_bill_reservation_lookup
          ON local_billing_reference_reservations (consumer_id, bill_date, status);

        CREATE TABLE IF NOT EXISTS handheld_assignments_cache (
            schedule_id INTEGER NOT NULL,
            consumer_id INTEGER NOT NULL,
            acct_no TEXT,
            assignment_order INTEGER,
            reading_route_id TEXT,
            zone_name TEXT,
            schedule_date TEXT,
            schedule_due_date TEXT,
            billing_cycle TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            reading_status TEXT NOT NULL DEFAULT 'pending',
            reading_sync_status TEXT NOT NULL DEFAULT 'pending',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (schedule_id, consumer_id)
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
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
        with self._connect() as conn:
            conn.executescript(sql)
            self._ensure_columns(
                conn,
                "sync_queue_meter_readings",
                {
                    "backend_status": "TEXT NOT NULL DEFAULT 'pending'",
                    "backend_synced_at": "TEXT",
                },
            )
            existing_queue_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(sync_queue_meter_readings)").fetchall()
            }
            legacy_status_column = "supa" + "base_status"
            legacy_synced_column = "supa" + "base_synced_at"
            if legacy_status_column in existing_queue_columns:
                conn.execute(
                    f"UPDATE sync_queue_meter_readings SET backend_status = {legacy_status_column} "
                    "WHERE backend_status = 'pending'"
                )
            if legacy_synced_column in existing_queue_columns:
                conn.execute(
                    f"UPDATE sync_queue_meter_readings SET backend_synced_at = {legacy_synced_column} "
                    "WHERE backend_synced_at IS NULL"
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
                    "water_meter_fee": "REAL NOT NULL DEFAULT 0",
                    "connection_fee": "REAL NOT NULL DEFAULT 0",
                    "membership_fee": "REAL NOT NULL DEFAULT 0",
                },
            )
            self._ensure_columns(
                conn,
                "local_billing_reference_reservations",
                {
                    "schedule_id": "INTEGER",
                    "billing_cycle": "TEXT",
                    "due_date": "TEXT",
                    "late_fee": "REAL",
                },
            )
            self._ensure_columns(
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
                    "status": "TEXT NOT NULL DEFAULT 'Scheduled'",
                    "cached_consumer_count": "INTEGER NOT NULL DEFAULT 0",
                    "cache_verified_at": "TEXT",
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
        """
        with self._connect() as conn:
            for item in schedules or []:
                if not isinstance(item, dict):
                    continue
                schedule_id = item.get("Schedule_ID", item.get("schedule_id"))
                start_date = str(
                    item.get("Start_Date", item.get("start_date", item.get("Schedule_Date", item.get("schedule_date")))) or ""
                ).split("T", 1)[0].split(" ", 1)[0]
                due_date = str(
                    item.get("Due_Date") or item.get("due_date") or start_date
                ).split("T", 1)[0].split(" ", 1)[0]
                schedule_date = start_date
                billing_month = str(item.get("Billing_Month", item.get("billing_month")) or "").strip() or None
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
                        start_date,
                        due_date,
                        billing_month,
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
            bill_status, late_fee, water_meter_fee, connection_fee, membership_fee,
            previous_reading, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            meter_no = excluded.meter_no,
            acct_no = excluded.acct_no,
            name = COALESCE(NULLIF(NULLIF(NULLIF(TRIM(excluded.name), ''), 'Unknown'), 'unknown'), handheld_consumers_cache.name),
            address = COALESCE(NULLIF(TRIM(excluded.address), ''), handheld_consumers_cache.address),
            zone_name = excluded.zone_name,
            classification_id = excluded.classification_id,
            classification_name = excluded.classification_name,
            minimum_cubic = excluded.minimum_cubic,
            minimum_rate = excluded.minimum_rate,
            excess_rate_per_cubic = excluded.excess_rate_per_cubic,
            due_days = excluded.due_days,
            penalty_percent = excluded.penalty_percent,
            billing_month = COALESCE(NULLIF(TRIM(excluded.billing_month), ''), handheld_consumers_cache.billing_month),
            date_covered_from = COALESCE(NULLIF(TRIM(excluded.date_covered_from), ''), handheld_consumers_cache.date_covered_from),
            date_covered_to = COALESCE(NULLIF(TRIM(excluded.date_covered_to), ''), handheld_consumers_cache.date_covered_to),
            amount_due = excluded.amount_due,
            previous_balance = excluded.previous_balance,
            due_date = COALESCE(NULLIF(TRIM(excluded.due_date), ''), handheld_consumers_cache.due_date),
            penalty = excluded.penalty,
            previous_penalty = excluded.previous_penalty,
            total_after_due_date = excluded.total_after_due_date,
            bill_status = excluded.bill_status,
            late_fee = excluded.late_fee,
            water_meter_fee = excluded.water_meter_fee,
            connection_fee = excluded.connection_fee,
            membership_fee = excluded.membership_fee,
            previous_reading = excluded.previous_reading,
            updated_at = CURRENT_TIMESTAMP
        """
        with self._connect() as conn:
            for item in consumers:
                params = self._normalize_cached_consumer(item)
                if not params:
                    continue
                conn.execute(sql, params)
                schedule_id = item.get("schedule_id", item.get("Schedule_ID"))
                consumer_id = item.get("id") or item.get("consumer_id")
                if schedule_id not in (None, "") and consumer_id not in (None, ""):
                    raw_order = item.get("assignment_order", item.get("Assignment_Order"))
                    try:
                        assignment_order = int(float(raw_order)) if raw_order not in (None, "") else None
                    except (TypeError, ValueError):
                        assignment_order = None
                    raw_is_read = item.get("is_read")
                    is_read = 1 if str(raw_is_read).strip().lower() in {"1", "true", "yes"} else 0
                    conn.execute(
                        """
                        INSERT INTO handheld_assignments_cache (
                            schedule_id, consumer_id, acct_no, assignment_order, reading_route_id,
                            zone_name, schedule_date, schedule_due_date, billing_cycle,
                            is_read, reading_status, reading_sync_status, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(schedule_id, consumer_id) DO UPDATE SET
                            acct_no = excluded.acct_no,
                            assignment_order = excluded.assignment_order,
                            reading_route_id = excluded.reading_route_id,
                            zone_name = excluded.zone_name,
                            schedule_date = excluded.schedule_date,
                            schedule_due_date = excluded.schedule_due_date,
                            billing_cycle = excluded.billing_cycle,
                            is_read = excluded.is_read,
                            reading_status = excluded.reading_status,
                            reading_sync_status = excluded.reading_sync_status,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            int(schedule_id), int(consumer_id), str(item.get("acct_no") or ""), assignment_order,
                            str(item.get("reading_route_id", item.get("Reading_Route_ID")) or "") or None,
                            item.get("zone_name"),
                            item.get("schedule_date", item.get("Schedule_Date")),
                            item.get("schedule_due_date", item.get("Schedule_Due_Date")),
                            item.get("billing_cycle", item.get("Billing_Cycle")), is_read,
                            str(item.get("reading_status") or "pending"),
                            str(item.get("reading_sync_status") or "pending"),
                        ),
                    )
            conn.commit()

    def load_cached_consumers(self, zone_name: str | None = None) -> list[dict]:
        base = """
        SELECT hc.id, hc.id AS consumer_id, hc.meter_no, COALESCE(ha.acct_no, hc.acct_no) AS acct_no,
               hc.name, hc.address, COALESCE(ha.zone_name, hc.zone_name) AS zone_name,
               hc.classification_id, hc.classification_name,
               hc.minimum_cubic, hc.minimum_rate, hc.excess_rate_per_cubic, hc.due_days, hc.penalty_percent,
               hc.billing_month, hc.date_covered_from, hc.date_covered_to,
               hc.amount_due, hc.previous_balance, hc.due_date, hc.penalty, hc.previous_penalty,
               hc.total_after_due_date, hc.bill_status, hc.late_fee,
               hc.water_meter_fee, hc.connection_fee, hc.membership_fee, hc.previous_reading,
               ha.schedule_id, ha.assignment_order, ha.reading_route_id,
               ha.schedule_date, ha.schedule_due_date, ha.billing_cycle,
               ha.is_read, ha.reading_status, ha.reading_sync_status
        FROM handheld_consumers_cache hc
        LEFT JOIN handheld_assignments_cache ha ON ha.consumer_id = hc.id
        """
        params: tuple = ()
        if zone_name:
            base += " WHERE COALESCE(ha.zone_name, hc.zone_name) = ?"
            params = (zone_name,)
        base += " ORDER BY ha.schedule_id"
        with self._connect() as conn:
            rows = conn.execute(base, params).fetchall()
        return sorted((dict(row) for row in rows), key=_cached_assignment_sort_key)

    def get_or_create_bill_reservation(
        self,
        consumer_id: int,
        bill_date: str,
        reading_sync_id: str | None = None,
        *,
        schedule_id: int | str | None = None,
        billing_cycle: str | None = None,
        due_date: str | None = None,
        late_fee: float | int | str | None = None,
    ) -> dict:
        normalized_date = date.fromisoformat(str(bill_date)).isoformat()
        normalized_schedule_id = _safe_int(schedule_id, None) if schedule_id not in (None, "") else None
        normalized_cycle = str(billing_cycle or "").strip() or None
        parsed_due_date = _parse_date(due_date)
        normalized_due_date = parsed_due_date.isoformat() if parsed_due_date else None
        normalized_late_fee = _safe_float(late_fee, None) if late_fee not in (None, "") else None
        with self._connect() as conn:
            if normalized_schedule_id is not None:
                lookup_sql = """
                SELECT bill_sync_id, reading_sync_id, consumer_id, bill_date,
                       schedule_id, billing_cycle, due_date, late_fee,
                       billing_reference, status, bill_id
                FROM local_billing_reference_reservations
                WHERE consumer_id = ? AND schedule_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """
                lookup_params = (int(consumer_id), normalized_schedule_id)
            else:
                lookup_sql = """
                SELECT bill_sync_id, reading_sync_id, consumer_id, bill_date,
                       schedule_id, billing_cycle, due_date, late_fee,
                       billing_reference, status, bill_id
                FROM local_billing_reference_reservations
                WHERE consumer_id = ? AND bill_date = ? AND status IN ('Pending', 'Reserved')
                ORDER BY created_at DESC
                LIMIT 1
                """
                lookup_params = (int(consumer_id), normalized_date)
            row = conn.execute(lookup_sql, lookup_params).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE local_billing_reference_reservations
                    SET billing_cycle = COALESCE(?, billing_cycle),
                        due_date = COALESCE(?, due_date),
                        late_fee = COALESCE(?, late_fee),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE bill_sync_id = ?
                    """,
                    (normalized_cycle, normalized_due_date, normalized_late_fee, row["bill_sync_id"]),
                )
                conn.commit()
                refreshed = conn.execute(
                    "SELECT * FROM local_billing_reference_reservations WHERE bill_sync_id = ?",
                    (row["bill_sync_id"],),
                ).fetchone()
                return dict(refreshed)
            bill_sync_id = str(uuid.uuid4())
            stable_reading_sync_id = str(reading_sync_id or uuid.uuid4())
            conn.execute(
                """
                INSERT INTO local_billing_reference_reservations (
                    bill_sync_id, reading_sync_id, consumer_id, schedule_id,
                    billing_cycle, bill_date, due_date, late_fee, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending')
                """,
                (
                    bill_sync_id, stable_reading_sync_id, int(consumer_id), normalized_schedule_id,
                    normalized_cycle, normalized_date, normalized_due_date, normalized_late_fee,
                ),
            )
            conn.commit()
        return {
            "bill_sync_id": bill_sync_id,
            "reading_sync_id": stable_reading_sync_id,
            "consumer_id": int(consumer_id),
            "schedule_id": normalized_schedule_id,
            "billing_cycle": normalized_cycle,
            "bill_date": normalized_date,
            "due_date": normalized_due_date,
            "late_fee": normalized_late_fee,
            "billing_reference": None,
            "status": "Pending",
            "bill_id": None,
        }

    def save_reserved_reference(self, bill_sync_id: str, billing_reference: str) -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE local_billing_reference_reservations
                SET billing_reference = ?, status = 'Reserved', updated_at = CURRENT_TIMESTAMP
                WHERE bill_sync_id = ?
                """,
                (billing_reference, bill_sync_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("The local billing reservation draft no longer exists.")
            conn.commit()

    def mark_bill_reservation_used(self, bill_sync_id: str, bill_id: int | str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE local_billing_reference_reservations
                SET status = 'Used', bill_id = ?, used_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE bill_sync_id = ?
                """,
                (bill_id, bill_sync_id),
            )
            conn.commit()

    def enqueue_operation(
        self,
        operation: str,
        payload: dict,
        *,
        backend_status: str = "pending",
    ) -> dict:
        operation_id = payload.get("operation_id") or str(uuid.uuid4())
        reading_id = payload.get("reading_id") or str(uuid.uuid4())
        payload["operation_id"] = operation_id
        payload["reading_id"] = reading_id
        sql = """
        INSERT INTO sync_queue_meter_readings (
            operation, operation_id, reading_id, consumer_id, reading_date, payload, status, backend_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        overall_status = self._combined_status(backend_status)
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
                    backend_status,
                ),
            )
            row = conn.execute(
                """
                SELECT id, operation_id, reading_id, status, backend_status, created_at
                FROM sync_queue_meter_readings
                WHERE id = ?
                """,
                (cur.lastrowid,),
            ).fetchone()
            conn.commit()
        return dict(row) if row else {}

    def list_pending(self, target: str | None = None) -> list[dict]:
        sql = """
        SELECT id, operation, operation_id, reading_id, consumer_id, reading_date, payload, status,
               backend_status, retries, last_error, created_at
        FROM sync_queue_meter_readings
        WHERE backend_status IN ('pending', 'failed')
        """
        sql += " ORDER BY id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [self._deserialize_row(row) for row in rows]

    def mark_target_synced(self, queue_id: int, target: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sync_queue_meter_readings
                SET backend_status='synced', backend_synced_at=CURRENT_TIMESTAMP, last_error=NULL
                WHERE id = ?
                """,
                (queue_id,),
            )
            self._refresh_queue_status(conn, queue_id)
            conn.commit()

    def mark_target_failed(self, queue_id: int, target: str, reason: str) -> None:
        scoped_reason = f"backend: {reason}"[:1000]
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sync_queue_meter_readings
                SET backend_status='failed', retries=retries+1, last_error=?
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
        scoped_reason = f"backend: {reason}"[:1000]
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sync_queue_meter_readings
                SET backend_status='conflict', conflict_reason=?, server_payload=?
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


class BackendApiClient:
    """HTTPS client for the Node backend exposed through Tailscale Funnel."""

    def __init__(self, cfg: SyncConfig):
        base_url = cfg.backend_api_base_url.rstrip("/")
        if base_url.endswith("/api"):
            self._root_url = base_url[:-4]
            self._api_url = base_url
        else:
            self._root_url = base_url
            self._api_url = f"{base_url}/api" if base_url else ""
        self._url = self._api_url or self._root_url
        self._meter_reader_id: int | None = None
        self._session_token = ""
        self._device_id = str(cfg.device_id or "").strip()

    def _req(
        self,
        method: str,
        path: str,
        *,
        query: dict | None = None,
        payload: dict | list | None = None,
        api_route: bool = True,
    ) -> tuple[int, object]:
        base_url = self._api_url if api_route else self._root_url
        normalized_path = path if path.startswith("/") else f"/{path}"
        if api_route and normalized_path.startswith("/api/"):
            normalized_path = normalized_path[4:]
        url = f"{base_url}{normalized_path}"
        if query:
            clean_query = {key: value for key, value in query.items() if value not in (None, "")}
            if clean_query:
                url += "?" + parse.urlencode(clean_query)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._session_token:
            headers["Authorization"] = f"Bearer {self._session_token}"
        req = request.Request(
            url,
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("utf-8").strip()
                return resp.getcode(), json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8").strip() if exc.fp else ""
            try:
                return exc.code, json.loads(raw) if raw else {"error": str(exc)}
            except Exception:
                return exc.code, {"error": raw or str(exc)}
        except Exception as exc:
            return 0, {"error": str(exc)}

    @staticmethod
    def _message(data: object, fallback: str) -> str:
        if isinstance(data, dict):
            return str(data.get("message") or data.get("error") or fallback)
        return fallback

    def _request_failure(self, status: int, path: str, data: object, fallback: str) -> RuntimeError:
        status_text = "Connection error" if status == 0 else f"HTTP {status}"
        return RuntimeError(f"{status_text} {path}: {self._message(data, fallback)}")

    def _is_missing_record(self, status: int, data: object) -> bool:
        return status == 404 and "cannot get /api/" not in self._message(data, "").lower()

    def is_online(self) -> bool:
        status, _ = self._req("GET", "/health", api_route=False)
        return 200 <= status < 300

    def authenticate_meter_reader(self, username: str, password: str) -> dict:
        status, data = self._req("POST", "/api/login", payload={"username": username, "password": password})
        if status >= 400 or status == 0 or not isinstance(data, dict) or not data.get("success"):
            raise ValueError(self._message(data, "Invalid username or password."))
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        if int(user.get("role_id") or 0) != 3:
            raise PermissionError("This account is not an active Meter Reader.")
        account_id = user.get("id") or user.get("account_id")
        self._meter_reader_id = int(account_id) if account_id not in (None, "") else None
        token_sources = (data, data.get("data") if isinstance(data.get("data"), dict) else {}, user)
        self._session_token = next(
            (
                str(source.get(key)).strip()
                for source in token_sources
                for key in (
                    "token", "access_token", "accessToken", "auth_token", "authToken",
                    "session_token", "sessionToken", "jwt",
                )
                if source.get(key) not in (None, "")
            ),
            "",
        )
        return {
            "id": account_id,
            "account_id": account_id,
            "username": user.get("username"),
            "name": user.get("fullName") or user.get("full_name") or user.get("username"),
            "full_name": user.get("fullName") or user.get("full_name") or user.get("username"),
            "contact_number": str(user.get("contact_number") or "").strip(),
            "role_id": user.get("role_id"),
            "account_status": "Active",
            "reader_id": str(account_id or ""),
            "session_token": self._session_token,
        }

    def set_authenticated_session(self, token: str | None, meter_reader_id: int | str | None = None) -> None:
        self._session_token = str(token or "").strip()
        self._meter_reader_id = int(meter_reader_id) if meter_reader_id not in (None, "") else None

    @staticmethod
    def _validate_reserved_reference(bill_sync_id: str, bill_date: str, billing_reference: str) -> None:
        try:
            normalized_date = date.fromisoformat(str(bill_date))
        except (TypeError, ValueError) as exc:
            raise ValueError("bill_date must use YYYY-MM-DD format.") from exc
        try:
            parsed_sync_id = uuid.UUID(str(bill_sync_id))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("bill_sync_id must be a UUID v4 value.") from exc
        if parsed_sync_id.version != 4:
            raise ValueError("bill_sync_id must be a UUID v4 value.")
        if not re.fullmatch(r"SLR[0-9]{10}", str(billing_reference or "")):
            raise ValueError("The backend returned an invalid billing_reference.")
        if billing_reference[3:7] != f"{normalized_date.year:04d}":
            raise ValueError("The billing reference year does not match bill_date.")

    def reserve_billing_reference(self, bill_sync_id: str, bill_date: str) -> dict:
        if not self._session_token:
            raise PermissionError("A current Meter Reader session is required to reserve a billing reference. Log in online again.")
        if not self._device_id:
            raise RuntimeError("HANDHELD_DEVICE_ID is not configured for this device.")
        try:
            normalized_date = date.fromisoformat(str(bill_date)).isoformat()
            parsed_sync_id = uuid.UUID(str(bill_sync_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("A UUID v4 bill_sync_id and YYYY-MM-DD bill_date are required.") from exc
        if parsed_sync_id.version != 4:
            raise ValueError("bill_sync_id must be a UUID v4 value.")
        request_payload = {
            "bill_sync_id": str(parsed_sync_id),
            "bill_date": normalized_date,
            "device_id": self._device_id,
        }
        status, data = self._req(
            "POST",
            "/api/handheld/billing-references/reserve",
            payload=request_payload,
        )
        if status == 409:
            raise ValueError(self._message(data, "Billing-reference reservation conflicts with the pending bill."))
        if status >= 400 or status == 0 or not isinstance(data, dict) or not data.get("success"):
            raise self._request_failure(
                status,
                "/api/handheld/billing-references/reserve",
                data,
                "Billing-reference reservation failed.",
            )
        billing_reference = str(data.get("billing_reference") or "").strip()
        self._validate_reserved_reference(str(parsed_sync_id), normalized_date, billing_reference)
        reservation = data.get("reservation") if isinstance(data.get("reservation"), dict) else {}
        if reservation:
            if str(reservation.get("bill_sync_id") or "") != str(parsed_sync_id):
                raise ValueError("The backend reservation returned a different bill_sync_id.")
            if str(reservation.get("bill_date") or "")[:10] != normalized_date:
                raise ValueError("The backend reservation returned a different bill_date.")
        return {**data, "billing_reference": billing_reference}

    def load_reading_schedules(
        self,
        meter_reader_id: int | str,
        date_from: str,
        date_to: str,
        status: str = "Scheduled",
    ) -> list[dict]:
        http_status, data = self._req(
            "GET",
            "/api/reading-schedules",
            query={
                "meter_reader_id": meter_reader_id,
                "date_from": date_from,
                "date_to": date_to,
                "status": status or "Scheduled",
            },
        )
        if http_status >= 400 or http_status == 0:
            raise self._request_failure(http_status, "/api/reading-schedules", data, "Backend reading schedule lookup failed.")
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def load_assigned_consumers(
        self,
        meter_reader_id: int | str | None = None,
        zone_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        status, data = self._req(
            "GET",
            "/api/handheld/consumers",
            query={
                "meter_reader_id": meter_reader_id,
                "zone_name": zone_name,
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        if status >= 400 or status == 0:
            raise self._request_failure(status, "/api/handheld/consumers", data, "Backend assigned-consumer lookup failed.")
        return [
            _flatten_backend_bill_context(row)
            for row in data
            if isinstance(row, dict)
        ] if isinstance(data, list) else []

    def get_consumer_context(self, consumer_id: int) -> dict:
        status, data = self._req("GET", f"/api/handheld/consumers/{int(consumer_id)}/context")
        if self._is_missing_record(status, data):
            return {}
        if status >= 400 or status == 0 or not isinstance(data, dict):
            path = f"/api/handheld/consumers/{int(consumer_id)}/context"
            raise self._request_failure(status, path, data, "Backend consumer-context lookup failed.")
        return _flatten_backend_bill_context(data)

    def find_existing_reading(self, consumer_id: int, reading_date: str) -> dict | None:
        status, data = self._req(
            "GET",
            "/api/handheld/readings/existing",
            query={"consumer_id": int(consumer_id), "reading_date": reading_date},
        )
        if self._is_missing_record(status, data):
            return None
        if status >= 400 or status == 0:
            raise self._request_failure(status, "/api/handheld/readings/existing", data, "Backend reading lookup failed.")
        return data if isinstance(data, dict) and data else None

    def save_reading_bundle(self, payload: dict) -> dict:
        merged = dict(payload)
        if self._meter_reader_id is not None:
            merged.setdefault("meter_reader_id", self._meter_reader_id)
        bill_sync_id = str(merged.get("bill_sync_id") or "").strip()
        bill_date = str(merged.get("bill_date") or merged.get("reading_date") or "").strip()[:10]
        billing_reference = str(merged.get("billing_reference") or "").strip()
        self._validate_reserved_reference(bill_sync_id, bill_date, billing_reference)
        bill = _build_bill_payload(merged, merged, 0)
        bill.pop("reading_id", None)
        bill.update({
            "sync_id": bill_sync_id,
            "bill_date": bill_date,
            "billing_reference": billing_reference,
        })
        reading_payload = dict(merged)
        for device_only_field in ("bill_sync_id", "bill_date", "billing_reference"):
            reading_payload.pop(device_only_field, None)
        status, data = self._req(
            "POST",
            "/api/handheld/reading-bundles",
            payload={"reading": reading_payload, "bill": bill},
        )
        if status == 409:
            raise ValueError(self._message(data, "The reserved billing reference conflicts with this bill."))
        if status >= 400 or status == 0 or not isinstance(data, dict):
            raise self._request_failure(status, "/api/handheld/reading-bundles", data, "Backend reading sync failed.")
        if not isinstance(data.get("bill"), dict):
            raise RuntimeError("Backend reading sync succeeded but did not return the authoritative response.bill.")
        saved_bill = data["bill"]
        if str(saved_bill.get("sync_id") or "") != bill_sync_id:
            raise RuntimeError("Backend reading sync returned a bill with a different sync_id.")
        if str(saved_bill.get("billing_reference") or "") != billing_reference:
            raise RuntimeError("Backend reading sync returned a different billing_reference.")
        return data

    def upsert_meter_reading(self, payload: dict) -> dict:
        result = self.save_reading_bundle(payload)
        row = result.get("meterreading") if isinstance(result, dict) else None
        return row if isinstance(row, dict) else {}


class HandheldSyncDataAccess:
    """Online/offline data access through the backend API and local SQLite queue."""

    def __init__(self, local_store: LocalSyncStore, remote_store):
        self.local = local_store
        self.remote = remote_store
        self.operation_lock = threading.RLock()
        self._worker_lock = threading.Lock()
        self._runtime_audit: list[dict] = []
        self.last_pre_reservation_result = {
            "ready": 0, "reserved": 0, "skipped": 0, "failed": 0, "errors": [],
        }
        self._worker_stop = threading.Event()
        self._worker: threading.Thread | None = None
        self.local.ensure_schema()

    def _endpoint(self) -> str:
        return str(getattr(self.remote, "_url", "") or "")

    def _audit(self, queue_id: int | None, status: str, message: str, payload: dict | None = None) -> None:
        try:
            self.local.log_audit(queue_id, status, message, payload)
        except Exception as audit_exc:
            fallback = {
                "queue_id": queue_id,
                "status": status,
                "message": message + "\n\n" + format_sync_error("Writing sync audit log", audit_exc),
                "payload": payload or {},
                "created_at": _utc_now_iso(),
            }
            self._runtime_audit.insert(0, fallback)
            del self._runtime_audit[50:]

    @classmethod
    def from_env(cls, fail_fast: bool = False) -> "HandheldSyncDataAccess":
        cfg = SyncConfig.from_env(fail_fast=fail_fast)
        return cls(SQLiteLocalSyncStore(cfg), BackendApiClient(cfg))

    def is_online(self) -> bool:
        return bool(self.remote and self.remote.is_online())

    def getConsumerContext(self, consumer_id: int) -> dict:
        if self.is_online():
            try:
                context = self.remote.get_consumer_context(int(consumer_id))
                if context:
                    self.local.cache_consumers([context])
                    return context
            except Exception as exc:
                self.local.log_audit(None, "failed", f"Backend API context lookup failed: {exc}")
        for row in self.local.load_cached_consumers(None):
            try:
                if int(row.get("id")) == int(consumer_id):
                    return row
            except (TypeError, ValueError):
                continue
        return {}

    def preReserveAssignedBills(self, consumers: list[dict]) -> dict:
        """Reserve stable references for known scheduled bills while connectivity exists."""
        result = {"ready": 0, "reserved": 0, "skipped": 0, "failed": 0, "errors": []}
        if not self.remote or not self.remote.is_online():
            self.last_pre_reservation_result = result
            return result
        for item in consumers or []:
            if not isinstance(item, dict):
                result["skipped"] += 1
                continue
            consumer_id = item.get("consumer_id", item.get("id"))
            schedule_id = item.get("schedule_id", item.get("Schedule_ID"))
            bill_date = (
                item.get("bill_date")
                or item.get("schedule_date")
                or item.get("start_date")
                or item.get("Schedule_Date")
                or item.get("Start_Date")
            )
            billing_cycle = item.get("billing_cycle") or item.get("billing_month") or item.get("Billing_Month")
            due_date = item.get("schedule_due_date") or item.get("due_date") or item.get("Due_Date")
            late_fee = item.get("late_fee")
            if late_fee in (None, ""):
                late_fee = item.get("penalty_percent", item.get("Late_Fee_Percentage"))
            if consumer_id in (None, "") or schedule_id in (None, "") or not _parse_date(bill_date):
                result["skipped"] += 1
                continue
            try:
                existing = self.local.get_or_create_bill_reservation(
                    int(consumer_id),
                    _parse_date(bill_date).isoformat(),
                    schedule_id=schedule_id,
                    billing_cycle=billing_cycle,
                    due_date=due_date,
                    late_fee=late_fee,
                )
                already_ready = bool(existing.get("billing_reference"))
                prepared = self.prepareBillingReference(
                    int(consumer_id),
                    str(existing["bill_date"]),
                    schedule_id=schedule_id,
                    billing_cycle=billing_cycle,
                    due_date=due_date,
                    late_fee=late_fee,
                )
                if prepared.get("billing_reference"):
                    result["ready"] += 1
                    if not already_ready:
                        result["reserved"] += 1
            except Exception as exc:
                result["failed"] += 1
                result["errors"].append(f"Consumer {consumer_id}, schedule {schedule_id}: {exc}")
        self._audit(None, "success" if not result["failed"] else "failed", "Prepared offline billing references", result)
        self.last_pre_reservation_result = result
        return result

    def loadAssignedConsumers(
        self,
        meter_reader_id: int | str | None = None,
        zone_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        **kwargs,
    ) -> list[dict]:
        effective_reader_id = meter_reader_id or kwargs.get("meterReaderId") or kwargs.get("reader_id")
        effective_zone_name = zone_name or kwargs.get("zoneName")
        if not date_from or not date_to:
            default_from, default_to = _device_schedule_window()
            date_from = date_from or default_from
            date_to = date_to or default_to

        if self.is_online():
            try:
                schedules: list[dict] = []
                if effective_reader_id not in (None, ""):
                    for schedule_status in ("Scheduled", "In Progress", "Completed"):
                        try:
                            schedules.extend(
                                self.remote.load_reading_schedules(
                                    effective_reader_id,
                                    date_from,
                                    date_to,
                                    schedule_status,
                                )
                            )
                        except Exception:
                            # Some backend versions do not accept Completed as a filter.
                            if schedule_status != "Completed":
                                raise
                    self.local.cache_reading_schedules(schedules, effective_reader_id, date_from, date_to)

                consumers = self.remote.load_assigned_consumers(
                    effective_reader_id,
                    effective_zone_name,
                    date_from,
                    date_to,
                )
                if consumers:
                    self.local.cache_consumers(consumers)
                    reservation_result = self.preReserveAssignedBills(consumers)
                    self.local.log_audit(
                        None,
                        "success",
                        "Loaded assigned consumers from Backend API",
                        {
                            "count": len(consumers),
                            "schedule_count": len(schedules),
                            "offline_references_ready": reservation_result["ready"],
                            "offline_reference_failures": reservation_result["failed"],
                        },
                    )
                    return consumers
                self.local.log_audit(
                    None,
                    "failed",
                    "Backend API returned no assigned consumers; using local cache",
                    {"schedule_count": len(schedules)},
                )
            except Exception as exc:
                self.local.log_audit(None, "failed", f"Backend API load failed; using local cache: {exc}")

        cached = self.local.load_cached_consumers(effective_zone_name)
        self.local.log_audit(None, "success", "Loaded assigned consumers from local cache", {"count": len(cached)})
        return cached

    def authenticateMeterReader(self, username: str, password: str) -> dict:
        if not self.remote or not self.remote.is_online():
            raise RuntimeError("Backend API is unavailable for meter reader login.")
        return self.remote.authenticate_meter_reader(username, password)

    def setAuthenticatedSession(self, token: str | None, meter_reader_id: int | str | None = None) -> None:
        if self.remote and hasattr(self.remote, "set_authenticated_session"):
            self.remote.set_authenticated_session(token, meter_reader_id)

    def reserveBillingReference(self, bill_sync_id: str, bill_date: str) -> dict:
        with self.operation_lock:
            if not self.remote or not self.remote.is_online():
                raise RuntimeError(
                    "The Backend API must be online before a billing reference can be reserved or printed."
                )
            result = self.remote.reserve_billing_reference(bill_sync_id, bill_date)
            self._audit(
                None,
                "success",
                "Reserved billing reference from Backend API",
                {
                    "bill_sync_id": bill_sync_id,
                    "bill_date": bill_date,
                    "billing_reference": result.get("billing_reference"),
                },
            )
            return result

    def prepareBillingReference(
        self,
        consumer_id: int,
        bill_date: str,
        *,
        schedule_id: int | str | None = None,
        billing_cycle: str | None = None,
        due_date: str | None = None,
        late_fee: float | int | str | None = None,
    ) -> dict:
        with self.operation_lock:
            draft = self.local.get_or_create_bill_reservation(
                int(consumer_id),
                bill_date,
                schedule_id=schedule_id,
                billing_cycle=billing_cycle,
                due_date=due_date,
                late_fee=late_fee,
            )
            bill_sync_id = str(draft["bill_sync_id"])
            normalized_date = str(draft["bill_date"])
            if draft.get("billing_reference"):
                return draft
            if not self.remote or not self.remote.is_online():
                raise RuntimeError(
                    "No pre-reserved billing reference is available for this scheduled bill. "
                    "Connect briefly and sync assigned routes before going offline."
                )
            result = self.remote.reserve_billing_reference(bill_sync_id, normalized_date)
            billing_reference = str(result.get("billing_reference") or "")
            self.local.save_reserved_reference(bill_sync_id, billing_reference)
            prepared = {
                **draft,
                "billing_reference": billing_reference,
                "status": "Reserved",
            }
            self._audit(
                None,
                "success",
                "Reserved and persisted billing reference from Backend API",
                prepared,
            )
            return prepared

    @staticmethod
    def _normalize_reading(payload: dict) -> dict:
        reading = dict(payload)
        reading.setdefault("reading_id", str(uuid.uuid4()))
        reading.setdefault("operation_id", str(uuid.uuid4()))
        reading.setdefault("created_at", _utc_now_iso())
        reading.setdefault("updated_at", _utc_now_iso())
        reading.setdefault("reading_date", datetime.now(timezone.utc).date().isoformat())
        return reading

    def _queue_for_sync(self, operation: str, reading: dict) -> dict:
        return self.local.enqueue_operation(operation, reading, backend_status="pending")

    def queueMeterReading(self, payload: dict) -> dict:
        with self.operation_lock:
            reading = self._normalize_reading(payload)
            queued = self._queue_for_sync("create", reading)
            _update_local_reading_state(reading.get("reading_id"), "pending", "valid")
            self.local.log_audit(queued["id"], "pending", "Queued reading for manual sync", reading)
            return {"status": "queued", "queue": queued, "reading": reading}

    def _save_or_queue(self, operation: str, payload: dict) -> dict:
        reading = self._normalize_reading(payload)
        queued = self._queue_for_sync(operation, reading)
        _update_local_reading_state(reading.get("reading_id"), "pending", "valid")
        if not self.is_online():
            self.local.log_audit(queued["id"], "pending", f"Queued offline {operation} operation", reading)
            return {"status": "queued", "queue": queued, "reading": reading}
        try:
            remote = self.remote.save_reading_bundle(reading)
            self.local.mark_target_synced(queued["id"], "backend")
            if reading.get("bill_sync_id") and hasattr(self.local, "mark_bill_reservation_used"):
                saved_bill = remote.get("bill") if isinstance(remote, dict) else {}
                self.local.mark_bill_reservation_used(
                    str(reading["bill_sync_id"]),
                    saved_bill.get("bill_id") if isinstance(saved_bill, dict) else None,
                )
            _update_local_reading_state(reading.get("reading_id"), "synced", "valid")
            self.local.log_audit(
                queued["id"],
                "success",
                "Reading synced to Backend API",
                {"reading_id": reading["reading_id"]},
            )
            return {
                "status": "synced",
                "remote": {"Backend API": remote},
                "reading": reading,
                "errors": [],
                "queue": queued,
            }
        except ValueError as exc:
            self.local.mark_conflict(queued["id"], str(exc), target="backend")
            _update_local_reading_state(reading.get("reading_id"), "conflict", "rejected")
            self.local.log_audit(queued["id"], "conflict", f"Backend API rejected the reserved bill: {exc}", reading)
            return {
                "status": "conflict",
                "queue": queued,
                "reading": reading,
                "errors": [str(exc)],
            }
        except Exception as exc:
            self.local.mark_target_failed(queued["id"], "backend", str(exc))
            _update_local_reading_state(reading.get("reading_id"), "failed", "valid")
            self.local.log_audit(queued["id"], "failed", f"Backend API save failed, queued for retry: {exc}", reading)
            return {"status": "queued", "queue": queued, "reading": reading}

    def saveMeterReading(self, payload: dict) -> dict:
        with self.operation_lock:
            return self._save_or_queue("create", payload)

    def updateMeterReading(self, payload: dict) -> dict:
        with self.operation_lock:
            return self._save_or_queue("update", payload)

    def listPendingSyncReadings(self) -> list[dict]:
        return self.local.list_pending("backend")

    def listPendingBackendReadings(self) -> list[dict]:
        return self.listPendingSyncReadings()

    def get_recent_audit_entries(self, limit: int = 20) -> list[dict]:
        try:
            stored = self.local.get_recent_audit(limit=limit)
        except Exception as exc:
            stored = [{
                "status": "failed",
                "message": format_sync_error("Reading sync logs from SQLite", exc),
                "created_at": _utc_now_iso(),
            }]
        return (list(self._runtime_audit) + stored)[:limit]

    def get_last_successful_sync_time(self) -> str | None:
        for row in self.get_recent_audit_entries(limit=100):
            if str(row.get("status", "")).lower() == "success" and "synced" in str(row.get("message", "")).lower():
                return str(row.get("created_at")) if row.get("created_at") else None
        return None

    def get_sync_snapshot(self) -> dict:
        pending = self.listPendingSyncReadings()
        online = self.is_online()
        last_sync = self.get_last_successful_sync_time()
        return {
            "status": "Online" if online else "Offline",
            "pending_count": len(pending),
            "has_failed": any(row.get("status") == "failed" for row in pending),
            "save_target": (
                "Local SQLite Queue (Backend API retry pending)"
                if pending
                else "Backend API auto-sync on change"
                if online
                else "Local SQLite Queue (offline)"
            ),
            "backup_state": "PostgreSQL managed by Backend API",
            "last_sync_time": last_sync,
            "backend_online": online,
            "backend_pending_count": len(pending),
            "backend_last_sync_time": last_sync,
        }

    def syncPendingReadings(self, **_ignored) -> dict:
        with self.operation_lock:
            return self._sync_pending_readings()

    def _sync_pending_readings(self) -> dict:
        if not self.is_online():
            diagnostic = format_sync_error(
                "Checking Backend API connectivity",
                "Backend API is unreachable or returned an unsuccessful health response.",
                self._endpoint(),
            )
            self._audit(None, "failed", diagnostic)
            return {"status": "offline", "synced": 0, "failed": 0, "conflicts": 0, "errors": [diagnostic]}

        pending = self.listPendingSyncReadings()
        self._audit(
            None,
            "pending",
            f"Stage: Preparing upload\nPending readings: {len(pending)}\nEndpoint: {self._endpoint()}",
            {"pending_count": len(pending), "endpoint": self._endpoint()},
        )
        synced = 0
        failed = 0
        conflicts = 0
        errors: list[str] = []
        for row in pending:
            queue_id = row["id"]
            payload = dict(row["payload"])
            try:
                existing = self.remote.find_existing_reading(payload["consumer_id"], payload["reading_date"])
                same_sync_id = bool(
                    existing
                    and str(existing.get("sync_id") or "") == str(payload.get("reading_id") or "")
                )
                if (
                    existing
                    and not same_sync_id
                    and existing.get("updated_at")
                    and payload.get("updated_at")
                    and str(existing["updated_at"]) > str(payload["updated_at"])
                ):
                    reason = "Server has a newer reading for the same consumer and date."
                    self.local.mark_conflict(queue_id, reason, existing, target="backend")
                    _update_local_reading_state(payload.get("reading_id"), "conflict", "rejected")
                    self._audit(queue_id, "conflict", f"Stage: Checking server version\nProblem: {reason}", {"local": payload, "server": existing})
                    conflicts += 1
                    continue

                remote_result = self.remote.save_reading_bundle(payload)
                self.local.mark_target_synced(queue_id, "backend")
                if payload.get("bill_sync_id") and hasattr(self.local, "mark_bill_reservation_used"):
                    saved_bill = remote_result.get("bill") if isinstance(remote_result, dict) else {}
                    self.local.mark_bill_reservation_used(
                        str(payload["bill_sync_id"]),
                        saved_bill.get("bill_id") if isinstance(saved_bill, dict) else None,
                    )
                _update_local_reading_state(payload.get("reading_id"), "synced", "valid")
                self._audit(
                    queue_id,
                    "success",
                    f"Stage: Uploading reading\nResult: Backend API and PostgreSQL accepted the reading.\nConsumer ID: {payload.get('consumer_id')}\nReading ID: {payload.get('reading_id')}",
                    {"reading_id": payload.get("reading_id")},
                )
                synced += 1
            except ValueError as exc:
                self.local.mark_conflict(queue_id, str(exc), target="backend")
                _update_local_reading_state(payload.get("reading_id"), "conflict", "rejected")
                diagnostic = format_sync_error("Validating queued reading", exc, self._endpoint())
                self._audit(queue_id, "conflict", diagnostic, payload)
                errors.append(diagnostic)
                conflicts += 1
            except Exception as exc:
                diagnostic = format_sync_error(
                    f"Uploading reading for consumer {payload.get('consumer_id', 'unknown')}",
                    exc,
                    self._endpoint(),
                )
                try:
                    self.local.mark_target_failed(queue_id, "backend", str(exc))
                    _update_local_reading_state(payload.get("reading_id"), "failed", "valid")
                except Exception as queue_exc:
                    diagnostic += "\n\n" + format_sync_error("Updating the local retry queue", queue_exc)
                self._audit(queue_id, "failed", diagnostic, payload)
                errors.append(diagnostic)
                failed += 1

        result = {"status": "done", "synced": synced, "failed": failed, "conflicts": conflicts, "errors": errors}
        summary_status = "success" if failed == 0 and conflicts == 0 else "failed"
        self._audit(
            None,
            summary_status,
            f"Stage: Sync finished\nSynced: {synced}\nFailed: {failed}\nConflicts: {conflicts}\nPending after sync: {len(self.listPendingSyncReadings())}",
            result,
        )
        return result

    def start_sync_worker(self, interval_seconds: int = BACKGROUND_SYNC_INTERVAL_SECONDS) -> None:
        with self._worker_lock:
            if self._worker and self._worker.is_alive():
                return
            self._worker_stop.clear()

            def _run():
                while not self._worker_stop.is_set():
                    try:
                        self.syncPendingReadings()
                    except Exception as exc:
                        self._audit(None, "failed", format_sync_error("Background sync worker", exc, self._endpoint()))
                    self._worker_stop.wait(max(60, interval_seconds))

            self._worker = threading.Thread(target=_run, daemon=True, name="handheld-sync-worker")
            self._worker.start()

    def stop_sync_worker(self) -> None:
        with self._worker_lock:
            worker = self._worker
            self._worker_stop.set()
            if worker and worker.is_alive() and worker is not threading.current_thread():
                worker.join(timeout=2.0)
            if self._worker is worker:
                self._worker = None

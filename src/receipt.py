"""Receipt formatting, preview, and Linux printer integration helpers."""

from __future__ import annotations

import datetime
import errno
import os
import shutil
import subprocess
import tempfile
import tkinter as tk

FONT_FAMILY = "Montserrat"
RAW_PRINTER_DEVICE = "/dev/usb/lp0"
RECEIPT_WIDTH = 32


def _format_reading(value: float | int | str) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f"{numeric:.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _center_text(value: str) -> str:
    return str(value).center(RECEIPT_WIDTH)


def _receipt_line(char: str = "-") -> str:
    return char * RECEIPT_WIDTH


def _field_line(label: str, value, width: int = 11) -> str:
    return f" {label:<{width}}: {value}"


def _money_line(label: str, value: float) -> str:
    return f" {label:<12}: PHP {value:>8.2f}"


def _percent_line(label: str, value: float) -> str:
    return f" {label:<11}: {value:>8.2f}%"


def _wrap_field_lines(label: str, value, width: int = 11, indent: int | None = None) -> list[str]:
    text = str(value if value not in (None, "") else "N/A")
    prefix = f" {label:<{width}}: "
    remaining = max(8, RECEIPT_WIDTH - len(prefix))
    continuation_indent = " " * (indent if indent is not None else len(prefix))
    lines: list[str] = []
    current = text.strip()
    first = True
    while current:
        if len(current) <= remaining:
            lines.append((prefix if first else continuation_indent) + current)
            break
        split_at = current.rfind(" ", 0, remaining + 1)
        if split_at <= 0:
            split_at = remaining
        chunk = current[:split_at].rstrip()
        lines.append((prefix if first else continuation_indent) + chunk)
        current = current[split_at:].lstrip()
        first = False
    if not lines:
        lines.append(prefix.rstrip())
    return lines


def _require_float(consumer: dict, field_name: str) -> float:
    value = consumer.get(field_name)
    if value is None or value == "":
        raise ValueError(f"Missing synced billing field: {field_name}")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid synced billing field: {field_name}") from exc


def _require_int(consumer: dict, field_name: str) -> int:
    value = consumer.get(field_name)
    if value is None or value == "":
        raise ValueError(f"Missing synced billing field: {field_name}")
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid synced billing field: {field_name}") from exc


def _require_billing_profile(consumer: dict) -> None:
    if not consumer.get("classification_id"):
        raise ValueError("Billing data is not synced for this consumer yet. Sync from the backend API before printing.")
    if not (consumer.get("classification_name") or "").strip():
        raise ValueError("Billing data is not synced for this consumer yet. Sync from the backend API before printing.")
    for field_name in (
        "minimum_cubic",
        "minimum_rate",
        "excess_rate_per_cubic",
        "due_days",
    ):
        if consumer.get(field_name) is None or consumer.get(field_name) == "":
            raise ValueError(f"Billing data is incomplete for this consumer. Missing synced field: {field_name}")


def _parse_date(value: str) -> datetime.date:
    raw = str(value).strip()
    if not raw:
        raise ValueError("Billing data is incomplete for this consumer. Missing synced field: due_date")
    raw = raw.split("T", 1)[0].split(" ", 1)[0]
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("Billing data has an invalid due_date value.") from exc


def _display_date(value, default: str = "N/A") -> str:
    if value in (None, ""):
        return default
    raw = str(value).strip()
    if not raw:
        return default
    raw = raw.split("T", 1)[0].split(" ", 1)[0]
    try:
        return datetime.date.fromisoformat(raw).isoformat()
    except ValueError:
        return raw


def _billing_month_text(consumer: dict, reference_date: datetime.date) -> str:
    raw = str(consumer.get("billing_month") or "").strip()
    if raw:
        return raw
    return reference_date.strftime("%B %Y")


def _billing_period_text(consumer: dict, reference_date: datetime.date) -> str:
    start_keys = (
        "date_covered_from",
        "billing_period_from",
        "previous_reading_date",
        "last_reading_date",
        "latest_reading_date",
    )
    end_keys = (
        "date_covered_to",
        "billing_period_to",
        "current_reading_date",
        "reading_date",
    )
    start_value = "N/A"
    for key in start_keys:
        start_value = _display_date(consumer.get(key), default="N/A")
        if start_value != "N/A":
            break
    end_value = _display_date(None, default=reference_date.isoformat())
    for key in end_keys:
        candidate = _display_date(consumer.get(key), default="")
        if candidate:
            end_value = candidate
            break
    if start_value == "N/A":
        raw_billing_month = str(consumer.get("billing_month") or "").strip()
        if raw_billing_month:
            try:
                month_anchor = datetime.datetime.strptime(raw_billing_month, "%B %Y").date()
                start_value = month_anchor.replace(day=1).isoformat()
            except ValueError:
                start_value = "N/A"
    if start_value == "N/A":
        start_value = reference_date.replace(day=1).isoformat()
    return f"{start_value} to {end_value}"


def _previous_bill_text(previous: float, carried_previous_bill: float) -> str:
    if previous <= 0:
        return "None"
    return f"PHP {carried_previous_bill:.2f}"


def _calculate_penalty(
    consumer: dict,
    current_bill: float,
    total_amount: float,
    due_date: datetime.date,
    reference_date: datetime.date,
) -> tuple[float, float, str, str]:
    late_fee = consumer.get("late_fee")
    late_fee_percent = 10.0 if late_fee in (None, "") else _require_float(consumer, "late_fee")
    bill_status = str(consumer.get("bill_status") or "Unpaid").strip()
    is_overdue = reference_date > due_date and bill_status.lower() != "paid"
    applied_penalty = round(current_bill * (late_fee_percent / 100.0), 2) if is_overdue else 0.0
    penalty_source = "current bill penalty" if is_overdue else "not yet due"
    total_after_due_date = round(total_amount + applied_penalty, 2)
    return applied_penalty, total_after_due_date, penalty_source, bill_status


def _optional_money(consumer: dict, field_name: str) -> float:
    value = consumer.get(field_name)
    if value in (None, ""):
        return 0.0
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def apply_authoritative_bill(consumer: dict, bill: dict) -> dict:
    """Overlay a backend-calculated bill onto consumer display metadata."""
    snapshot = dict(consumer)
    snapshot.update(bill)
    if bill.get("status") not in (None, ""):
        snapshot["bill_status"] = bill["status"]
    snapshot["_authoritative_bill"] = True
    return snapshot


def _carried_previous_bill(consumer: dict) -> tuple[float, float, str]:
    bill_status = str(consumer.get("bill_status") or "Unpaid").strip() or "Unpaid"
    if bill_status.lower() == "paid":
        return 0.0, 0.0, bill_status

    # Server-provided aggregates are display values. Never derive a fresh
    # penalty from amount_due, because it may already include older penalties.
    return (
        _optional_money(consumer, "previous_balance"),
        _optional_money(consumer, "previous_penalty"),
        bill_status,
    )

def _compute_bill(consumption: float, consumer: dict) -> tuple[float, int, float, float]:
    minimum_cubic = _require_int(consumer, "minimum_cubic")
    minimum_rate = _require_float(consumer, "minimum_rate")
    excess_rate = _require_float(consumer, "excess_rate_per_cubic")
    safe_consumption = max(consumption, 0)
    if safe_consumption <= minimum_cubic:
        current_bill = minimum_rate
    else:
        current_bill = minimum_rate + ((safe_consumption - minimum_cubic) * excess_rate)
    return round(current_bill, 2), minimum_cubic, minimum_rate, excess_rate


def build_receipt_text(
    consumer: dict,
    previous: float,
    present: float,
    exception: str,
    reader_name: str = "Field Reader",
    reading_date: str | datetime.date | None = None,
) -> str:
    _require_billing_profile(consumer)
    consumption = present - previous
    calculated_current_bill, minimum_cubic, minimum_rate, excess_rate = _compute_bill(consumption, consumer)
    authoritative = bool(consumer.get("_authoritative_bill"))
    current_bill = calculated_current_bill
    if authoritative:
        for field_name in ("current_month_amount", "original_amount", "water_charge", "class_cost"):
            if consumer.get(field_name) not in (None, ""):
                current_bill = _optional_money(consumer, field_name)
                break

    now = datetime.datetime.now()
    reference_date = _parse_date(str(reading_date)) if reading_date not in (None, "") else now.date()
    date_str = reference_date.isoformat()
    time_str = now.strftime("%I:%M %p")
    due_days = _require_int(consumer, "due_days")
    carried_previous_bill, previous_penalty, previous_bill_status = _carried_previous_bill(consumer)
    calculated_amount_due = round(current_bill + carried_previous_bill + previous_penalty, 2)
    amount_due = (
        _optional_money(consumer, "amount_due")
        if authoritative and consumer.get("amount_due") not in (None, "")
        else calculated_amount_due
    )
    due_date_value = consumer.get("due_date")
    due_date_obj = _parse_date(due_date_value) if due_date_value not in (None, "") else (reference_date + datetime.timedelta(days=due_days))
    due_date = due_date_obj.isoformat()
    if authoritative:
        penalty = (
            _optional_money(consumer, "current_penalty")
            if consumer.get("current_penalty") not in (None, "")
            else _optional_money(consumer, "penalty")
        )
        after_due = (
            _optional_money(consumer, "total_after_due_date")
            if consumer.get("total_after_due_date") not in (None, "")
            else round(amount_due + penalty, 2)
        )
        penalty_source = "backend bill"
        bill_status = str(consumer.get("status") or consumer.get("bill_status") or "Unpaid")
    else:
        penalty, after_due, penalty_source, bill_status = _calculate_penalty(
            consumer, current_bill, amount_due, due_date_obj, reference_date
        )
    bill_status = previous_bill_status
    late_fee = consumer.get("late_fee")
    late_fee_percent = 10.0 if late_fee in (None, "") else _require_float(consumer, "late_fee")
    billing_month = _billing_month_text(consumer, reference_date)
    billing_period = _billing_period_text(consumer, reference_date)
    previous_bill = _previous_bill_text(previous, carried_previous_bill)
    address = consumer.get("address") or consumer.get("consumer_address") or "N/A"

    divider = _receipt_line("-")
    border = _receipt_line("=")

    lines = [
        border,
        _center_text("SAN LORENZO RUIZ WATERWORKS"),
        _center_text("Water Billing System"),
        border,
        _center_text(str(consumer.get("acct_no", "N/A"))),
        _center_text(str(consumer.get("name", "N/A"))),
        divider,
    ]
    lines.extend(_wrap_field_lines("Address", address))
    lines += [
        _field_line("Meter No", consumer.get("meter_no", "N/A")),
        _field_line("Class", consumer.get("classification_name", "N/A")),
        divider,
        _field_line("Bill Month", billing_month, width=11),
    ]
    lines.extend(_wrap_field_lines("Coverage", billing_period, width=11))
    lines += [
        _field_line("Present", _format_reading(present), width=11),
        _field_line("Previous", _format_reading(previous), width=11),
        _field_line("Use", f"{_format_reading(consumption)} m3", width=11),
        _field_line("Prev Bill", previous_bill, width=11),
    ]

    if exception and exception.strip().lower() not in {"none", ""}:
        lines.extend(_wrap_field_lines("Exception", exception))

    lines += [
        divider,
        _field_line("Min Cubic", minimum_cubic),
        _money_line("Min Rate", minimum_rate),
        _money_line("Excess Rate", excess_rate),
        _money_line("Current Bill", current_bill),
        _money_line("Due Pen(10%)", penalty),
        _money_line("Previous", carried_previous_bill),
        _money_line("Prev Pen(10%)", previous_penalty),
        border,
        _money_line("TOTAL DUE", amount_due),
        _money_line("AFTER DUE", after_due),
        _field_line("Due Date", due_date),
        border,
        _field_line("Date", date_str),
        _field_line("Time", time_str),
        _field_line("Reader", reader_name),
        divider,
        _center_text("Thank you!"),
        border,
        "",
        "",
    ]
    return "\n".join(lines)


def can_use_system_printer() -> bool:
    if os.name == "nt":
        return False
    return shutil.which("lp") is not None or shutil.which("lpr") is not None


def build_test_receipt_text(now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now()
    return "\n".join(
        [
            "SAN LORENZO RUIZ WATERWORKS SYSTEM",
            "Billing and Payment System",
            "",
            "TEST PRINT",
            "",
            "Printer connection successful.",
            "Device: Meter Reader Handheld",
            "Status: Ready",
            "",
            f"Date: {now.strftime('%Y-%m-%d')}",
            f"Time: {now.strftime('%I:%M %p')}",
            "",
            "--------------------------------",
            "This is a printer test receipt.",
            "--------------------------------",
        ]
    )


def build_reprint_receipt_text(
    original_receipt_text: str,
    original_printed_at: str | None = None,
    reprint_at: datetime.datetime | None = None,
) -> str:
    reprint_at = reprint_at or datetime.datetime.now()
    header_lines = [
        "DUPLICATE COPY",
        "",
    ]
    if original_printed_at:
        header_lines.append(f"Original Print Date: {original_printed_at}")
    header_lines.append(f"Reprint Date: {reprint_at.strftime('%Y-%m-%d %I:%M %p')}")
    header_lines.extend(["", original_receipt_text.rstrip(), "", "", "", ""])
    return "\n".join(header_lines)


def _build_test_receipt_escpos(now: datetime.datetime | None = None) -> bytes:
    now = now or datetime.datetime.now()
    nl = b"\n"
    init = b"\x1b@"
    align_left = b"\x1ba\x00"
    align_center = b"\x1ba\x01"
    bold_on = b"\x1bE\x01"
    bold_off = b"\x1bE\x00"
    double_size = b"\x1d!\x11"
    normal_size = b"\x1d!\x00"
    feed_lines = b"\n\n\n\n"

    body = build_test_receipt_text(now)
    body_lines = body.splitlines()
    heading_lines = body_lines[:2]
    remaining_lines = body_lines[2:]

    chunks: list[bytes] = [init, align_center, bold_on, double_size]
    for line in heading_lines:
        chunks.append(line.encode("ascii", errors="replace") + nl)
    chunks.extend([normal_size, bold_off, nl, bold_on])
    chunks.append("TEST PRINT".encode("ascii") + nl)
    chunks.extend([bold_off, nl, align_left])
    for line in remaining_lines[2:]:
        chunks.append(line.encode("ascii", errors="replace") + nl)
    chunks.append(feed_lines)
    return b"".join(chunks)


def print_test_receipt(device_path: str = RAW_PRINTER_DEVICE) -> str:
    if os.name == "nt":
        raise RuntimeError("Raw USB printer testing is available only on the Raspberry Pi Linux device.")

    if not os.path.exists(device_path):
        raise RuntimeError("Printer device /dev/usb/lp0 was not found.")

    print_data = _build_test_receipt_escpos()
    try:
        with open(device_path, "wb") as printer:
            printer.write(print_data)
            printer.flush()
    except PermissionError as exc:
        raise RuntimeError("Permission denied while accessing /dev/usb/lp0.") from exc
    except BlockingIOError as exc:
        raise RuntimeError("Printer device /dev/usb/lp0 is busy.") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("Printer device /dev/usb/lp0 was not found.") from exc
    except OSError as exc:
        if exc.errno in {errno.EBUSY, errno.EAGAIN}:
            raise RuntimeError("Printer device /dev/usb/lp0 is busy.") from exc
        if exc.errno in {errno.ENODEV, errno.ENXIO}:
            raise RuntimeError("Printer appears to be disconnected from /dev/usb/lp0.") from exc
        if exc.errno in {errno.EIO, errno.EPIPE}:
            raise RuntimeError("Write failure while sending data to /dev/usb/lp0.") from exc
        raise RuntimeError(str(exc) or "Unknown printer write failure.") from exc

    return build_test_receipt_text()


def send_to_system_printer(receipt_text: str, printer_name: str | None = None) -> None:
    if not can_use_system_printer():
        raise RuntimeError("No Linux print command is available. Install CUPS with lp or lpr on the Raspberry Pi.")

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", newline="\n", suffix=".txt") as handle:
            handle.write(receipt_text)
            tmp_path = handle.name

        printer = printer_name or os.environ.get("GP58_PRINTER_NAME", "").strip()
        lp_path = shutil.which("lp")
        if lp_path:
            cmd = [lp_path]
            if printer:
                cmd += ["-d", printer]
            cmd.append(tmp_path)
        else:
            lpr_path = shutil.which("lpr")
            if lpr_path is None:
                raise RuntimeError("No Linux print command is available.")
            cmd = [lpr_path]
            if printer:
                cmd += ["-P", printer]
            cmd.append(tmp_path)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Unknown printer error").strip()
            raise RuntimeError(detail)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Printing timed out while waiting for the GP58 printer.") from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def preview_receipt(parent, receipt_text: str):
    win = tk.Toplevel(parent)
    win.title("Receipt Preview")
    win.resizable(False, False)
    win.configure(bg="#FFFFFF")
    win.attributes("-topmost", True)
    win.grab_set()

    w, h = 380, 560
    win.update_idletasks()
    sx = (win.winfo_screenwidth() - w) // 2
    sy = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{sx}+{sy}")

    tk.Label(
        win,
        text="Receipt Preview",
        font=(FONT_FAMILY, 11, "bold"),
        bg="#1565C0",
        fg="#FFFFFF",
        pady=8,
    ).pack(fill="x")

    frame = tk.Frame(win, bg="#FFFFFF")
    frame.pack(fill="both", expand=True, padx=14, pady=8)

    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")

    text_widget = tk.Text(
        frame,
        font=("Courier New", 10),
        bg="#F8F9FA",
        fg="#1A1A2E",
        relief="flat",
        bd=0,
        wrap="none",
        yscrollcommand=scrollbar.set,
        padx=8,
        pady=8,
    )
    text_widget.pack(fill="both", expand=True)
    scrollbar.config(command=text_widget.yview)

    text_widget.insert("1.0", receipt_text)
    text_widget.config(state="disabled")

    btn_frame = tk.Frame(win, bg="#FFFFFF")
    btn_frame.pack(fill="x", padx=14, pady=(0, 12))

    tk.Button(
        btn_frame,
        text="Close",
        font=(FONT_FAMILY, 11, "bold"),
        bg="#1A2744",
        fg="#FFFFFF",
        activebackground="#2D2D4A",
        activeforeground="#FFFFFF",
        relief="flat",
        bd=0,
        cursor="hand2",
        pady=10,
        command=win.destroy,
    ).pack(fill="x", expand=True)

    return win


def show_receipt(parent, consumer: dict, previous: int, present: int, exception: str, reader_name: str = "Field Reader"):
    receipt_text = build_receipt_text(consumer, previous, present, exception, reader_name)
    return preview_receipt(parent, receipt_text)

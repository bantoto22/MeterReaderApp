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
        raise ValueError("Billing data is not synced for this consumer yet. Sync from PostgreSQL/Supabase before printing.")
    if not (consumer.get("classification_name") or "").strip():
        raise ValueError("Billing data is not synced for this consumer yet. Sync from PostgreSQL/Supabase before printing.")
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
    applied_penalty = round(current_bill * (late_fee_percent / 100.0), 2)
    penalty_source = "projected after-due penalty"
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

def _carried_previous_bill(consumer: dict) -> tuple[float, float, str]:
    bill_status = str(consumer.get("bill_status") or "Unpaid").strip() or "Unpaid"
    previous_balance = _optional_money(consumer, "previous_balance")
    if bill_status.lower() == "paid":
        return 0.0, 0.0, bill_status

    unpaid_amount = _optional_money(consumer, "amount_due")
    unpaid_penalty = _optional_money(consumer, "penalty")
    previous_penalty = _optional_money(consumer, "previous_penalty")
    late_fee = consumer.get("late_fee")
    late_fee_percent = 10.0 if late_fee in (None, "") else _require_float(consumer, "late_fee")

    latest_unpaid_principal = max(0.0, unpaid_amount - previous_penalty)
    carried = max(previous_balance, latest_unpaid_principal)
    computed_previous_penalty = round(carried * (late_fee_percent / 100.0), 2)
    stored_previous_penalty = previous_penalty if previous_balance > 0 else max(previous_penalty, unpaid_penalty)
    carried_penalty = max(stored_previous_penalty, computed_previous_penalty)
    return carried, carried_penalty, bill_status

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
    current_bill, minimum_cubic, minimum_rate, excess_rate = _compute_bill(consumption, consumer)

    now = datetime.datetime.now()
    reference_date = _parse_date(str(reading_date)) if reading_date not in (None, "") else now.date()
    date_str = reference_date.isoformat()
    time_str = now.strftime("%I:%M %p")
    due_days = _require_int(consumer, "due_days")
    carried_previous_bill, previous_penalty, previous_bill_status = _carried_previous_bill(consumer)
    amount_due = round(current_bill + carried_previous_bill + previous_penalty, 2)
    due_date_value = consumer.get("due_date")
    due_date_obj = _parse_date(due_date_value) if due_date_value not in (None, "") else (reference_date + datetime.timedelta(days=due_days))
    due_date = due_date_obj.isoformat()
    penalty, after_due, penalty_source, bill_status = _calculate_penalty(consumer, current_bill, amount_due, due_date_obj, reference_date)
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
        _field_line("Address", address),
        _field_line("Meter No", consumer.get("meter_no", "N/A")),
        _field_line("Class", consumer.get("classification_name", "N/A")),
        divider,
        _field_line("Billing Month", billing_month, width=13),
        _field_line("Billing Period", billing_period, width=13),
        _field_line("Present Read", _format_reading(present), width=13),
        _field_line("Prev Read", _format_reading(previous), width=13),
        _field_line("Consumption", f"{_format_reading(consumption)} m3", width=13),
        _field_line("Prev Bill", previous_bill, width=13),
    ]

    if exception and exception.strip().lower() not in {"none", ""}:
        lines.append(_field_line("Exception", exception))

    lines += [
        divider,
        _field_line("Min Cubic", minimum_cubic),
        _money_line("Min Rate", minimum_rate),
        _money_line("Excess Rate", excess_rate),
        _money_line("Current Bill", current_bill),
        _money_line("Due Penalty(10%)", penalty),
        _money_line("Previous", carried_previous_bill),
        _money_line("Prev Penalty(10%)", previous_penalty),
        border,
        _money_line("TOTAL AMOUNT", amount_due),
        _money_line("After Due", after_due),
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

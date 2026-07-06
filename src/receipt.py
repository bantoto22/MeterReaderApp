"""Receipt formatting, preview, and Linux printer integration helpers."""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import tempfile
import tkinter as tk

FONT_FAMILY = "Montserrat"

DEFAULT_MINIMUM_CUBIC = 0
DEFAULT_MINIMUM_RATE = 50.00
DEFAULT_EXCESS_RATE = 7.50
DEFAULT_PENALTY_PERCENT = 10.0
DEFAULT_DUE_DAYS = 11


def _to_float(value, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _compute_bill(consumption: int, consumer: dict) -> tuple[float, int, float, float]:
    minimum_cubic = _to_int(consumer.get("minimum_cubic"), DEFAULT_MINIMUM_CUBIC)
    minimum_rate = _to_float(consumer.get("minimum_rate"), DEFAULT_MINIMUM_RATE)
    excess_rate = _to_float(consumer.get("excess_rate_per_cubic"), DEFAULT_EXCESS_RATE)
    safe_consumption = max(consumption, 0)
    if safe_consumption <= minimum_cubic:
        current_bill = minimum_rate
    else:
        current_bill = minimum_rate + ((safe_consumption - minimum_cubic) * excess_rate)
    return round(current_bill, 2), minimum_cubic, minimum_rate, excess_rate


def build_receipt_text(
    consumer: dict,
    previous: int,
    present: int,
    exception: str,
    reader_name: str = "Field Reader",
) -> str:
    consumption = present - previous
    current_bill, minimum_cubic, minimum_rate, excess_rate = _compute_bill(consumption, consumer)
    prev_balance = 0.00
    penalty_percent = _to_float(consumer.get("penalty_percent"), DEFAULT_PENALTY_PERCENT)
    due_days = _to_int(consumer.get("due_days"), DEFAULT_DUE_DAYS)
    penalty_rate = penalty_percent / 100.0
    penalty = round(current_bill * penalty_rate, 2)
    total_amount = round(current_bill + prev_balance + penalty, 2)
    after_due = round(total_amount + (total_amount * penalty_rate), 2)

    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%I:%M %p")
    due_date = (now + datetime.timedelta(days=due_days)).strftime("%Y-%m-%d")

    divider = "--------------------------------"
    border = "================================"

    lines = [
        border,
        " SAN LORENZO RUIZ WATERWORKS",
        "     Water Billing System",
        border,
        f" Account No : {consumer.get('acct_no', 'N/A')}",
        f" Name       : {consumer.get('name', 'N/A')}",
        f" Zone       : {consumer.get('zone_name', 'N/A')}",
        f" Class      : {consumer.get('classification_name', 'N/A')}",
        divider,
        f" Meter No   : {consumer.get('meter_no', 'N/A')}",
        f" Prev Read  : {previous}",
        f" Curr Read  : {present}",
        f" Consumption: {consumption} m3",
    ]

    if exception and exception.strip().lower() not in {"none", ""}:
        lines.append(f" Exception  : {exception}")

    lines += [
        divider,
        f" Min Cubic  : {minimum_cubic}",
        f" Min Rate   : PHP {minimum_rate:>8.2f}",
        f" Excess Rate: PHP {excess_rate:>8.2f}",
        f" Current Bill: PHP {current_bill:>8.2f}",
        f" Prev Balance: PHP {prev_balance:>8.2f}",
        f" Penalty {penalty_percent:>4.0f}%: PHP {penalty:>8.2f}",
        border,
        f" TOTAL AMOUNT: PHP {total_amount:>8.2f}",
        f" After Due   : PHP {after_due:>8.2f}",
        f" Due Date    : {due_date}",
        divider,
        f" Date  : {date_str}",
        f" Time  : {time_str}",
        f" Reader: {reader_name}",
        divider,
        "         Thank you!",
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

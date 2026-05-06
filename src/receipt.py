"""
receipt.py – Printable receipt for the Water Meter Reader app.

HOW TO INTEGRATE (tell your groupmate who handles meter_reader.py):
────────────────────────────────────────────────────────────────────
STEP 1 – Place receipt.py in the SAME folder as meter_reader.py

STEP 2 – Add this import at the TOP of meter_reader.py (after the other imports):
    from receipt import show_receipt

STEP 3 – Find the _simulate_printing() method in meter_reader.py:
    def _simulate_printing(self):
        time.sleep(2)
        self.after(0, self._show_success)

    Replace it with:
    def _simulate_printing(self):
        consumer  = self._current_consumer
        present   = int(self.present_var.get())
        previous  = consumer["previous_reading"]
        exception = self.exception_var.get()
        self.after(0, lambda: show_receipt(self, consumer, previous, present, exception))
        self.after(100, self._show_success)

That's all – no other changes needed anywhere else.
"""

import tkinter as tk
import datetime
import os
import tempfile
import subprocess
import sys

FONT_FAMILY = "Montserrat"

# ── Billing constants (adjust to match actual water rates) ─────────────────
BASE_RATE     = 7.50   # ₱ per m³
MINIMUM_BILL  = 50.00  # ₱ minimum monthly charge
PENALTY_RATE  = 0.10   # 10% penalty on overdue bill
DUE_DAYS      = 11     # reading date + 11 days = due date


def _compute_bill(consumption: int) -> float:
    """Compute current bill from consumption. Returns minimum if consumption is 0."""
    if consumption <= 0:
        return MINIMUM_BILL
    return max(MINIMUM_BILL, round(consumption * BASE_RATE, 2))


def show_receipt(parent, consumer: dict, previous: int, present: int, exception: str, reader_name: str = "Field Reader"):
    """
    Show a receipt preview window with real data, then allow printing.

    Parameters
    ----------
    parent       : tk.Widget  – the MeterReaderApp window (used as Toplevel parent)
    consumer     : dict       – from DB search, keys: acct_no, name, meter_no, zone_name
    previous     : int        – previous meter reading (from DB)
    present      : int        – present meter reading (entered by field reader)
    exception    : str        – e.g. "None", "Leaking", "Stuck Meter", etc.
    reader_name  : str        – name of the meter reader who took the reading
    """

    # ── Compute billing values ─────────────────────────────────────────
    consumption  = present - previous
    current_bill = _compute_bill(consumption)
    prev_balance = 0.00                              # wire to ledger DB if available
    penalty      = round(current_bill * PENALTY_RATE, 2)
    total_amount = round(current_bill + prev_balance + penalty, 2)
    after_due    = round(total_amount + (total_amount * PENALTY_RATE), 2)

    now      = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%I:%M %p")
    due_date = (now + datetime.timedelta(days=DUE_DAYS)).strftime("%Y-%m-%d")

    # Use provided reader name (passed from main app)

    # ── Build thermal-style receipt text ───────────────────────────────
    S1 = "--------------------------------"
    S2 = "================================"

    lines = [
        S2,
        " SAN LORENZO RUIZ WATERWORKS",
        "     Water Billing System",
        S2,
        f" Account No : {consumer.get('acct_no', 'N/A')}",
        f" Name       : {consumer.get('name', 'N/A')}",
        f" Zone       : {consumer.get('zone_name', 'N/A')}",
        S1,
        f" Meter No   : {consumer.get('meter_no', 'N/A')}",
        f" Prev Read  : {previous}",
        f" Curr Read  : {present}",
        f" Consumption: {consumption} m\u00b3",
    ]

    if exception and exception.strip().lower() not in ("none", ""):
        lines.append(f" Exception  : {exception}")

    lines += [
        S1,
        f" Current Bill: \u20b1{current_bill:>9.2f}",
        f" Prev Balance: \u20b1{prev_balance:>9.2f}",
        f" Penalty     : \u20b1{penalty:>9.2f}",
        S2,
        f" TOTAL AMOUNT: \u20b1{total_amount:>9.2f}",
        f" After Due   : \u20b1{after_due:>9.2f}",
        f" Due Date    : {due_date}",
        S1,
        f" Date  : {date_str}",
        f" Time  : {time_str}",
        f" Reader: {reader_name}",
        S1,
        "         Thank you!",
        S2,
    ]

    receipt_text = "\n".join(lines)

    # ── Preview window ─────────────────────────────────────────────────
    win = tk.Toplevel(parent)
    win.title("Receipt Preview")
    win.resizable(False, False)
    win.configure(bg="#FFFFFF")
    win.attributes("-topmost", True)
    win.grab_set()

    w, h = 380, 560
    win.update_idletasks()
    sx = (win.winfo_screenwidth()  - w) // 2
    sy = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{sx}+{sy}")

    # Header
    tk.Label(
        win, text="Receipt Preview",
        font=(FONT_FAMILY, 11, "bold"),
        bg="#1565C0", fg="#FFFFFF", pady=8
    ).pack(fill="x")

    # Receipt text area with scrollbar
    frame = tk.Frame(win, bg="#FFFFFF")
    frame.pack(fill="both", expand=True, padx=14, pady=8)

    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")

    text_widget = tk.Text(
        frame,
        font=("Courier New", 10),
        bg="#F8F9FA", fg="#1A1A2E",
        relief="flat", bd=0,
        wrap="none",
        yscrollcommand=scrollbar.set,
        padx=8, pady=8,
    )
    text_widget.pack(fill="both", expand=True)
    scrollbar.config(command=text_widget.yview)

    text_widget.insert("1.0", receipt_text)
    text_widget.config(state="disabled")   # read-only

    # Buttons
    btn_frame = tk.Frame(win, bg="#FFFFFF")
    btn_frame.pack(fill="x", padx=14, pady=(0, 12))

    tk.Button(
        btn_frame, text="\u2715  Close",
        font=(FONT_FAMILY, 11, "bold"),
        bg="#1A2744", fg="#FFFFFF",
        activebackground="#2D2D4A", activeforeground="#FFFFFF",
        relief="flat", bd=0, cursor="hand2",
        pady=10, command=win.destroy
    ).pack(fill="x", expand=True)

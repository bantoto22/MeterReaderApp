"""
Water Meter Reader - Flat UI Compact (Single Card Grouping)
A modern tkinter GUI for field meter reading on handheld devices.
Redesigned to fit tightly on a 480x660 screen with a single card group.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import math
import os
import platform
import re
import ctypes
import socket
import subprocess
from datetime import datetime, timezone
from PIL import Image, ImageTk

try:
    import ttkbootstrap as tb
except ImportError:
    tb = None
try:
    from .database import (
        init_db,
        search_consumer,
        search_consumers_by_zone,
        save_reading,
        get_zone_stats,
        get_all_zone_names,
        get_zone_consumers_with_status,
        get_latest_receipt_print,
        replace_consumers_from_sync,
        authenticate_user,
        get_all_users,
        save_receipt_print,
        seed_default_users,
    )
    from .receipt import build_receipt_text, can_use_system_printer, send_to_system_printer, show_receipt
    from .handheld_sync import HandheldSyncDataAccess, SyncConfig
except Exception:
    from database import (
        init_db,
        search_consumer,
        search_consumers_by_zone,
        save_reading,
        get_zone_stats,
        get_all_zone_names,
        get_zone_consumers_with_status,
        get_latest_receipt_print,
        replace_consumers_from_sync,
        authenticate_user,
        get_all_users,
        save_receipt_print,
        seed_default_users,
    )
    from receipt import build_receipt_text, can_use_system_printer, send_to_system_printer, show_receipt
    try:
        from handheld_sync import HandheldSyncDataAccess, SyncConfig
    except Exception:
        HandheldSyncDataAccess = None
        SyncConfig = None

# --- Load custom font (Montserrat) on Windows --------------------------------
def _load_custom_font():
    """Register a TTF font file so tkinter can use it by family name."""
    font_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "assets", "fonts", "Montserrat.ttf")
    font_path = os.path.abspath(font_path)

    try:
        if not os.path.exists(font_path):
            print(f"Custom font not found at: {font_path}")
            return

        system_name = platform.system()
        if system_name == "Windows":
            try:
                result = ctypes.windll.gdi32.AddFontResourceExW(font_path, 0x10, 0)
                if result == 0:
                    print(f"Windows font registration returned 0 for: {font_path}")
            except Exception as exc:
                print(f"Failed to register custom font on Windows: {exc}")
        else:
            print(f"Skipping Windows-only font loading on {system_name}")
    except Exception as exc:
        print(f"Custom font loading skipped due to error: {exc}")

_load_custom_font()


# --- Color palette ------------------------------------------------------------
BG_COLOR         = "#F4F7FB"
WHITE            = "#FFFFFF"
PRIMARY_BLUE     = "#2563EB"
HEADER_BLUE      = "#1E40AF"
TAB_DARK         = "#111827"
TAB_BLUE         = "#1F2937"
ACCENT_BLUE      = "#60A5FA"
DARK_TEXT         = "#111827"
MID_TEXT          = "#526176"
LIGHT_TEXT        = "#8A99AD"
PLACEHOLDER_CLR  = "#94A3B8"
BORDER_COLOR     = "#D8E1EC"
INPUT_BORDER     = "#C9D5E3"
INPUT_FOCUS      = ACCENT_BLUE
INPUT_BG         = "#F8FAFD"
DARK_BTN         = "#0F172A"
DARK_HOVER       = "#1E293B"
OVERLAY_DIM      = "#0F172A"
SUCCESS_GREEN    = "#10B981"
SUCCESS_TEXT     = "#10B981" 

# Consumption states
VALID_BG         = "#ECFDF5"
VALID_BORDER     = "#10B981"
VALID_TEXT        = "#047857"
WARNING_BG       = "#FFFBEB"
WARNING_BORDER   = "#F59E0B"
WARNING_TEXT      = "#B45309"
INVALID_BG       = "#FEF2F2"
INVALID_BORDER   = "#EF4444"
INVALID_TEXT      = "#B91C1C"

DEVICE_WIDTH     = 480
DEVICE_HEIGHT    = 750  # Perfectly fitted to screen size
FONT_FAMILY      = "Montserrat"

HIGH_CONSUMPTION_THRESHOLD = 500

# --- Phone Status Bar Colors -------------------------------------------------
STATUS_BAR_BG = "#0B1220"
STATUS_BAR_FG = "#FFFFFF"
BATTERY_LOW = "#E53935"
BATTERY_MED = "#F9A825"
BATTERY_HIGH = "#43A047"
SIGNAL_ACTIVE = "#43A047"
SIGNAL_INACTIVE = "#5A5A7A"
PAPER_OK = "#43A047"
PAPER_LOW = "#F9A825"
PAPER_OUT = "#E53935"
PAPER_JAM = "#C62828"

# --- Meter Reader Users -------------------------------------------------------
# Users are now stored in the database (users table)
# Default users seeded on first run:
#   reader1 / pass123 - Juan Santos (MR-001)
#   reader2 / pass456 - Maria Cruz (MR-002)


# --- Status Bar Widget (Phone-style) -----------------------------------------
class StatusBar(tk.Canvas):
    """Phone-style status bar with battery, signal, paper indicators, and live clock."""

    def __init__(self, parent, height=28, **kwargs):
        self._height = height
        self._battery_level = 85
        self._signal_strength = 4
        self._paper_status = "ok"  # ok, low, out, jam
        self._show_paper_warning = False

        super().__init__(parent, highlightthickness=0, bg=STATUS_BAR_BG, height=height, **kwargs)
        self.bind("<Configure>", self._redraw)
        self._start_clock()

    def _start_clock(self):
        """Start the live clock updater."""
        self._redraw()
        self.after(60000, self._start_clock)  # Update every minute

    def set_battery(self, level: int):
        """Set battery level (0-100)."""
        self._battery_level = max(0, min(100, level))
        self._redraw()

    def set_signal(self, strength: int):
        """Set signal strength (0-4)."""
        self._signal_strength = max(0, min(4, strength))
        self._redraw()

    def get_signal(self) -> int:
        return self._signal_strength

    def set_paper_status(self, status: str):
        """Set paper status: 'ok', 'low', 'out', 'jam'."""
        self._paper_status = status
        self._redraw()

    def get_paper_status(self) -> str:
        return self._paper_status

    def can_print(self) -> bool:
        """Check if printing is possible (paper not out or jammed)."""
        return self._paper_status not in ("out", "jam")

    def _redraw(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self._height

        # Background
        self.create_rectangle(0, 0, w, h, fill=STATUS_BAR_BG, outline="")

        padding = 10
        x_offset = padding

        # Signal strength indicator (left side)
        self._draw_signal_bars(x_offset, h // 2)
        x_offset += 35

        # Battery indicator
        self._draw_battery(w - padding - 30, h // 2)

        # Paper status indicator (center-right)
        self._draw_paper_status(w - padding - 90, h // 2)

        # Time display (centered)
        from datetime import datetime
        time_str = datetime.now().strftime("%I:%M %p")
        self.create_text(w // 2, h // 2, text=time_str, font=(FONT_FAMILY, 10), fill=STATUS_BAR_FG, anchor="center")

    def _draw_signal_bars(self, x, cy):
        """Draw signal strength bars (4 bars max)."""
        bar_width = 4
        bar_gap = 2
        heights = [6, 10, 14, 18]

        for i, h in enumerate(heights):
            color = SIGNAL_ACTIVE if i < self._signal_strength else SIGNAL_INACTIVE
            x1 = x + i * (bar_width + bar_gap)
            y1 = cy - h // 2
            x2 = x1 + bar_width
            y2 = cy + h // 2
            self.create_rectangle(x1, y1, x2, y2, fill=color, outline="")

    def _draw_battery(self, x, cy):
        """Draw battery icon with level."""
        # Battery body
        bw, bh = 24, 12
        x1, y1 = x - bw // 2, cy - bh // 2
        x2, y2 = x1 + bw, y1 + bh

        # Battery outline
        self.create_rectangle(x1, y1, x2, y2, fill=STATUS_BAR_BG, outline=STATUS_BAR_FG, width=1)
        # Battery tip
        self.create_rectangle(x2, cy - 3, x2 + 2, cy + 3, fill=STATUS_BAR_FG, outline="")

        # Battery fill level
        if self._battery_level > 50:
            color = BATTERY_HIGH
        elif self._battery_level > 20:
            color = BATTERY_MED
        else:
            color = BATTERY_LOW

        fill_width = (bw - 2) * self._battery_level / 100
        if fill_width > 0:
            self.create_rectangle(x1 + 1, y1 + 1, x1 + 1 + fill_width, y2 - 1, fill=color, outline="")

    def _draw_paper_status(self, x, cy):
        """Draw paper status indicator."""
        if self._paper_status == "ok":
            color = PAPER_OK
            text = "PAPER OK"
        elif self._paper_status == "low":
            color = PAPER_LOW
            text = "PAPER LOW"
        elif self._paper_status == "out":
            color = PAPER_OUT
            text = "PAPER OUT"
        else:  # jam
            color = PAPER_JAM
            text = "PAPER JAM"

        # Dot + label badge avoids unsupported emoji glyphs on Pi/Windows fonts.
        self.create_oval(x - 46, cy - 4, x - 38, cy + 4, fill=color, outline="")
        self.create_text(x - 32, cy, text=text, font=(FONT_FAMILY, 8, "bold"), fill=color, anchor="w")


# --- Login Screen ------------------------------------------------------------
class LoginScreen(tk.Frame):
    """Login screen for meter readers."""

    def __init__(self, parent, on_login_success, **kwargs):
        super().__init__(parent, bg=BG_COLOR, **kwargs)
        self._on_login_success = on_login_success
        self._build_ui()

    def _build_ui(self):
        self.pack_propagate(False)

        # Body area
        body = tk.Frame(self, bg="#E2E8F0")
        body.pack(fill="both", expand=True)

        # Main Login Card (simulating the mockup card)
        card = tk.Frame(body, bg="#F1F5F9", highlightthickness=0)
        card.place(relx=0.5, rely=0.5, anchor="center", width=420, height=660)

        # Ensure the card has rounded corner appearance or clean border
        card_inner = tk.Frame(card, bg="#F1F5F9")
        card_inner.pack(fill="both", expand=True, padx=24, pady=24)

        # Logo
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "images", "SLR logo 1.png")
        self.logo_photo = None
        if os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path)
                logo_img = logo_img.resize((80, 80), Image.Resampling.LANCZOS)
                self.logo_photo = ImageTk.PhotoImage(logo_img)
                logo_label = tk.Label(card_inner, image=self.logo_photo, bg="#F1F5F9")
                logo_label.pack(pady=(10, 10))
            except Exception as e:
                print(f"Error loading login logo: {e}")

        if not self.logo_photo:
            # Fallback Canvas Logo
            icon_canvas = tk.Canvas(card_inner, width=80, height=80, bg="#F1F5F9", highlightthickness=0)
            icon_canvas.pack(pady=(10, 10))
            icon_canvas.create_oval(5, 5, 75, 75, fill="#1D4ED8", outline="")
            icon_canvas.create_text(40, 40, text="💧", font=(FONT_FAMILY, 28), fill="white")

        # Titles
        tk.Label(card_inner, text="San Lorenzo Ruiz Waterworks System", font=(FONT_FAMILY, 15, "bold"),
                 bg="#F1F5F9", fg="#0F172A", wraplength=360, justify="center").pack(pady=(0, 4))
        
        tk.Label(card_inner, text="Water Billing and Payment Record Management System", font=(FONT_FAMILY, 10),
                 bg="#F1F5F9", fg="#475569", wraplength=360, justify="center").pack(pady=(0, 16))

        # Form card
        form_frame = tk.Frame(card_inner, bg="#F1F5F9")
        form_frame.pack(fill="x", pady=0)

        # Username
        tk.Label(form_frame, text="Username", font=(FONT_FAMILY, 11, "bold"),
                 bg="#F1F5F9", fg="#475569").pack(anchor="w", pady=(0, 4))

        self._username_var = tk.StringVar()
        self._username_entry = RoundedEntry(form_frame, placeholder="Enter your username",
                                          height=46, radius=8, font=(FONT_FAMILY, 11),
                                          bg="#FFFFFF", fg="#0F172A", border_color="#E2E8F0", textvariable=self._username_var)
        self._username_entry.pack(fill="x", pady=(0, 12))

        # Password
        tk.Label(form_frame, text="Password", font=(FONT_FAMILY, 11, "bold"),
                 bg="#F1F5F9", fg="#475569").pack(anchor="w", pady=(0, 4))

        self._password_var = tk.StringVar()
        self._password_entry = RoundedEntry(form_frame, placeholder="Enter your password",
                                            height=46, radius=8, font=(FONT_FAMILY, 11),
                                            bg="#FFFFFF", fg="#0F172A", border_color="#E2E8F0", textvariable=self._password_var)
        self._password_entry.entry.config(show="•")
        self._password_entry.pack(fill="x", pady=(0, 16))

        # Error message label
        self._error_label = tk.Label(form_frame, text="", font=(FONT_FAMILY, 9),
                                     bg="#F1F5F9", fg="#EF4444")
        self._error_label.pack(pady=(0, 8))

        # Login button
        login_btn = RoundedButton(form_frame, text="Log In", command=self._attempt_login,
                                  radius=8, bg_color="#2563EB", fg_color=WHITE, font=(FONT_FAMILY, 12, "bold"))
        login_btn.pack(fill="x", pady=(8, 0), ipady=8)
        # Bind Enter key
        self._password_entry.entry.bind("<Return>", lambda e: self._attempt_login())
        self._username_entry.entry.bind("<Return>", lambda e: self._password_entry.entry.focus())
        # Footer
        tk.Label(card_inner, text="© 2026 Municipality of San Lorenzo Ruiz", font=(FONT_FAMILY, 8),
                 bg="#F1F5F9", fg="#64748B").pack(side="bottom", pady=(10, 0))

    def set_loading_status(self, title: str, detail: str = ""):
        """Update bottom loading/status text on login screen."""
        if hasattr(self, "_loading_title_label"):
            self._loading_title_label.config(text=title)
        if hasattr(self, "_loading_detail_label"):
            self._loading_detail_label.config(text=detail)

    def hide_loading_status(self):
        """Hide loading/status panel after startup is complete."""
        if hasattr(self, "_loading_hint_frame") and self._loading_hint_frame.winfo_exists():
            self._loading_hint_frame.pack_forget()

    def _attempt_login(self):
        username = self._username_var.get().strip()
        password = self._password_var.get().strip()

        if not username or not password:
            self._error_label.config(text="Please enter both username and password")
            return

        # Check credentials against database
        user = authenticate_user(username, password)
        if user:
            self._error_label.config(text="")
            self._on_login_success(user)
            return

        self._error_label.config(text="Invalid username or password")
        self._shake_widget(self._username_entry)
        self._shake_widget(self._password_entry)

    def _shake_widget(self, widget):
        """Shake animation for invalid login."""
        original_x = widget.winfo_x()
        offsets = [5, -5, 4, -4, 3, -3, 2, -2, 0]
        delay = 0
        for offset in offsets:
            self.after(delay, lambda o=offset: widget.place_configure(x=original_x + o) if widget.winfo_manager() == 'place' else None)
            delay += 40

    def clear(self):
        """Clear the form fields."""
        self._username_var.set("")
        self._password_var.set("")
        self._error_label.config(text="")


# --- Rounded Entry Widget ----------------------------------------------------
class RoundedEntry(tk.Canvas):
    """An Entry widget wrapped in a canvas-drawn rounded rectangle."""

    def __init__(self, parent, radius=8, border_color=INPUT_BORDER,
                 focus_color=INPUT_FOCUS, bg=INPUT_BG, fg=DARK_TEXT,
                 placeholder="", font=None, justify="left",
                 textvariable=None, **kwargs):
        self._radius = radius
        self._border_color = border_color
        self._focus_color = focus_color
        self._entry_bg = bg
        self._placeholder = placeholder
        self._has_focus = False
        self._vcmd = None
        self._override_border = None

        height = kwargs.pop("height", 44)
        super().__init__(parent, highlightthickness=0, bg=parent["bg"],
                         height=height, **kwargs)

        self.bind("<Configure>", self._redraw)

        entry_font = font or (FONT_FAMILY, 12)
        self.entry = tk.Entry(self, font=entry_font, bg=bg, fg=fg,
                              relief="flat", bd=0, justify=justify,
                              highlightthickness=0, insertbackground=DARK_TEXT)
        if textvariable:
            self.entry.configure(textvariable=textvariable)

        self._entry_window = None
        self._is_placeholder_active = False

        if placeholder:
            self._is_placeholder_active = True
            self.entry.insert(0, placeholder)
            self.entry.configure(fg=PLACEHOLDER_CLR)

        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)

    def _redraw(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        r = self._radius

        if self._override_border: color = self._override_border
        elif self._has_focus:     color = self._focus_color
        else:                     color = self._border_color

        border_w = 2.5 if self._override_border else (2 if self._has_focus else 1.5)

        # Subtle inner shadow effect at the top for inputs
        self._draw_rr(2, 3, w - 2, h - 1, r, fill="#E2E8F0", outline="")
        self._draw_rr(2, 2, w - 2, h - 2, r, fill=self._entry_bg, outline=color, width=border_w)

        if self._entry_window:
            self.delete(self._entry_window)
        self._entry_window = self.create_window(
            r + 8, h // 2, anchor="w", window=self.entry,
            width=w - 2 * r - 16, height=h - 18)

    def _draw_rr(self, x1, y1, x2, y2, r, **kw):
        pts = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1, x1 + r, y1,
        ]
        return self.create_polygon(pts, smooth=True, **kw)

    def _on_focus_in(self, event=None):
        self._has_focus = True
        if self._placeholder and self._is_placeholder_active:
            self.entry.configure(validate="none")
            self.entry.delete(0, "end")
            self.entry.configure(fg=DARK_TEXT)
            self._is_placeholder_active = False
            if self._vcmd:
                self.entry.configure(validate="key", validatecommand=self._vcmd)
        self._redraw()

    def _on_focus_out(self, event=None):
        self._has_focus = False
        if self._placeholder and not self.entry.get():
            self.entry.configure(validate="none")
            self.entry.insert(0, self._placeholder)
            self.entry.configure(fg=PLACEHOLDER_CLR)
            self._is_placeholder_active = True
            if self._vcmd:
                self.entry.configure(validate="key", validatecommand=self._vcmd)
        self._redraw()

    def get(self):
        if self._is_placeholder_active: return ""
        return self.entry.get()

    def set_validate(self, vcmd, validate="key"):
        self._vcmd = vcmd
        self.entry.configure(validate=validate, validatecommand=vcmd)

    def set_border_color(self, color):
        self._override_border = color
        self._redraw()

    def clear_border_override(self):
        self._override_border = None
        self._redraw()


# --- Compact Checkbox -------------------------------------------------------
class CompactCheckbutton(tk.Canvas):
    """Small rounded checkbox chip with a comfortable touch target."""

    def __init__(self, parent, text, variable, command=None, **kwargs):
        super().__init__(
            parent,
            width=116,
            height=34,
            bg=parent["bg"],
            highlightthickness=0,
            takefocus=1,
            cursor="hand2",
            **kwargs,
        )
        self._text = text
        self._variable = variable
        self._command = command
        self._hovered = False
        self._variable.trace_add("write", self._on_variable_changed)
        self.bind("<Button-1>", self._toggle)
        self.bind("<Return>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Configure>", self._redraw)
        self.after_idle(self._redraw)

    def _draw_rr(self, x1, y1, x2, y2, radius, **kwargs):
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1, x1 + radius, y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

    def _redraw(self, event=None):
        self.delete("all")
        checked = bool(self._variable.get())
        width = max(1, self.winfo_width())
        chip_fill = "#DBEAFE" if checked and self._hovered else "#EFF6FF" if checked else "#F1F5F9" if self._hovered else BG_COLOR
        chip_outline = "#BFDBFE" if checked else chip_fill
        self._draw_rr(1, 1, width - 1, 33, 16, fill=chip_fill, outline=chip_outline, width=1)

        box_fill = PRIMARY_BLUE if checked else WHITE
        box_outline = PRIMARY_BLUE if checked else "#94A3B8"
        self._draw_rr(8, 7, 28, 27, 5, fill=box_fill, outline=box_outline, width=1)
        if checked:
            self.create_line(13, 17, 17, 21, 24, 12, fill=WHITE, width=2, capstyle="round", joinstyle="round")

        self.create_text(
            36,
            17,
            anchor="w",
            text=self._text,
            fill="#1D4ED8" if checked else MID_TEXT,
            font=(FONT_FAMILY, 10, "bold" if checked else "normal"),
        )

    def _toggle(self, event=None):
        self._variable.set(not bool(self._variable.get()))
        if self._command:
            self._command()
        return "break"

    def _on_variable_changed(self, *_args):
        self._redraw()

    def _on_enter(self, _event=None):
        self._hovered = True
        self._redraw()

    def _on_leave(self, _event=None):
        self._hovered = False
        self._redraw()


# --- GroupCard Container -----------------------------------------------------
class GroupCard(tk.Canvas):
    """A minimal Canvas container that renders a rounded flat card background."""

    def __init__(self, parent, radius=8, bg_color=WHITE, outline=BORDER_COLOR, padding=18, **kwargs):
        self._radius = radius
        self._bg_color = bg_color
        self._outline = outline
        self._padding = padding
        
        super().__init__(parent, highlightthickness=0, bg=parent["bg"], **kwargs)
        
        self.inner_frame = tk.Frame(self, bg=self._bg_color)
        self._window = self.create_window(padding, padding, anchor="nw", window=self.inner_frame)
        self.inner_frame.bind("<Configure>", self._on_frame_configure)
        self.bind("<Configure>", self._redraw)
        
    def _on_frame_configure(self, event):
        self.configure(height=event.height + 2 * self._padding)
        self._redraw()
        
    def _redraw(self, event=None):
        self.delete("bg_shape")
        self.delete("shadow")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1 or h <= 1: return
        r = self._radius
        self.itemconfig(self._window, width=max(1, w - 2 * self._padding))
        
        # Simulated drop shadow
        self._draw_rr(2, 3, w - 1, h, r, fill="#E6ECF4", outline="", tags="shadow")
        
        # Main card body
        self._draw_rr(1, 1, w - 2, h - 3, r, fill=self._bg_color, outline=self._outline, width=1, tags="bg_shape")
        
        self.tag_lower("bg_shape")
        self.tag_lower("shadow")
        
    def _draw_rr(self, x1, y1, x2, y2, r, **kw):
        pts = [
            x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
            x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
            x1, y2, x1, y2-r, x1, y1+r, x1, y1, x1+r, y1,
        ]
        return self.create_polygon(pts, smooth=True, **kw)


# --- Rounded Button Component ------------------------------------------------
class RoundedButton(tk.Canvas):
    """A Canvas-based button with rounded corners and a simulated shadow."""
    def __init__(self, parent, text, command, radius=10, bg_color=PRIMARY_BLUE, 
                 fg_color=WHITE, font=None, shadow_color="#CBD5E1", **kwargs):
        super().__init__(parent, highlightthickness=0, bg=parent["bg"], **kwargs)
        self.command = command
        self._radius = radius
        self._bg_color = bg_color
        self._current_bg = bg_color
        self._fg_color = fg_color
        self._font = font or (FONT_FAMILY, 14, "bold")
        self._shadow_color = shadow_color
        self.text = text
        
        self.bind("<Configure>", self._redraw)
        self.bind("<Button-1>", self._on_click)
        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        
    def _redraw(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        r = self._radius
        
        # Shadow
        self._draw_rr(2, 4, w - 2, h, r, fill=self._shadow_color)
        # Button Body
        self._draw_rr(2, 2, w - 2, h - 2, r, fill=self._current_bg)
        # Text
        self.create_text(w // 2, h // 2, text=self.text, font=self._font, fill=self._fg_color)
        
    def _draw_rr(self, x1, y1, x2, y2, r, **kw):
        pts = [
            x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
            x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
            x1, y2, x1, y2-r, x1, y1+r, x1, y1, x1+r, y1,
        ]
        return self.create_polygon(pts, smooth=True, **kw)
        
    def _on_click(self, event):
        self.command()

    def _hover_color(self):
        return {
            PRIMARY_BLUE: "#1D4ED8",
            TAB_DARK: "#1F2937",
            SUCCESS_GREEN: "#059669",
        }.get(self._bg_color, self._bg_color)

    def _on_enter(self, event=None):
        self.config(cursor="hand2")
        self._current_bg = self._hover_color()
        self._redraw()

    def _on_leave(self, event=None):
        self._current_bg = self._bg_color
        self._redraw()

    def _on_press(self, event=None):
        self._current_bg = "#172033" if self._bg_color == TAB_DARK else self._hover_color()
        self._redraw()

    def _on_release(self, event=None):
        self._current_bg = self._hover_color()
        self._redraw()
        
    @property
    def text(self):
        return getattr(self, "_text", "")
        
    @text.setter
    def text(self, value):
        self._text = value
        self._redraw()


# --- Rounded Key (Canvas-based animated keyboard key) -------------------------
class RoundedKey(tk.Canvas):
    """A Canvas-based keyboard key with rounded corners and hover/press animations."""
    def __init__(self, parent, text, command=None,
                 bg=None, hover=None, press=None, fg="#66C6FF",
                 font=None, radius=12, height=65, **kwargs):
        _bg     = bg    or "#253048"
        _hover  = hover or "#2E3B5C"
        _press  = press or "#3A4A70"
        super().__init__(parent, highlightthickness=0, bd=0,
                         width=1, height=height, bg=parent["bg"], **kwargs)
        self.command = command
        self._text = text
        self._bg_color   = _bg
        self._hover_color = _hover
        self._press_color = _press
        self._fg_color   = fg
        self._font       = font
        self._radius     = radius
        self._current    = _bg

        self.bind("<Configure>",      lambda e: self._draw())
        self.bind("<Enter>",          lambda e: self._set_state(self._hover_color))
        self.bind("<Leave>",          lambda e: self._set_state(self._bg_color))
        self.bind("<ButtonPress-1>",  lambda e: self._set_state(self._press_color))
        self.bind("<ButtonRelease-1>", self._on_release)

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
        pts = [
            x1+r, y1,  x2-r, y1,  x2, y1,  x2, y1+r,
            x2, y2-r,  x2, y2,    x2-r, y2, x1+r, y2,
            x1, y2,    x1, y2-r,  x1, y1+r, x1, y1,
        ]
        return self.create_polygon(pts, smooth=True, **kw)

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1 or h <= 1:
            return
        self._round_rect(2, 2, w-2, h-2, self._radius,
                         fill=self._current, outline="")
        self.create_text(w/2, h/2, text=self._text,
                         fill=self._fg_color, font=self._font)

    def _set_state(self, color):
        self._current = color
        self._draw()

    def _on_release(self, event):
        self._current = self._hover_color
        self._draw()
        w, h = self.winfo_width(), self.winfo_height()
        if 0 <= event.x <= w and 0 <= event.y <= h and self.command:
            self.command()

    def set_text(self, text):
        self._text = text
        self._draw()


# --- Modern Tab Button -------------------------------------------------------
class ModernTabButton(tk.Frame):
    """An animated, modern tab button with an active indicator and hover effects."""
    def __init__(self, parent, text, font, command, **kwargs):
        super().__init__(parent, bg=TAB_BLUE, cursor="hand2", **kwargs)
        self.command = command
        self.text = text
        self.base_font = font
        
        # Indicator line at the bottom
        self.indicator = tk.Frame(self, bg=TAB_BLUE, height=3)
        self.indicator.pack(side="bottom", fill="x")
        
        # Inner padding frame
        self.inner = tk.Frame(self, bg=TAB_BLUE)
        self.inner.pack(expand=True, fill="both")
        
        self.lbl = tk.Label(self.inner, text=text, font=(font[0], font[1], "normal"), bg=TAB_BLUE, fg="#A8B4C5")
        self.lbl.pack(expand=True)
        
        for w in (self, self.indicator, self.inner, self.lbl):
            w.bind("<Button-1>", lambda e: self.command())
            w.bind("<Enter>", self.on_enter)
            w.bind("<Leave>", self.on_leave)
            
        self.active = False
        
    def on_enter(self, e=None):
        if not self.active:
            self._set_colors("#263449", "#F1F5F9", TAB_BLUE)
            
    def on_leave(self, e=None):
        if not self.active:
            self._set_colors(TAB_BLUE, "#A8B4C5", TAB_BLUE)
            
    def _set_colors(self, bg, fg, ind):
        self.config(bg=bg)
        self.inner.config(bg=bg)
        self.indicator.config(bg=ind)
        self.lbl.config(bg=bg, fg=fg)
        
    def set_active(self, active):
        self.active = active
        if active:
            self._set_colors(TAB_DARK, WHITE, ACCENT_BLUE)
            self.lbl.config(font=(self.base_font[0], self.base_font[1], "bold"))
        else:
            self._set_colors(TAB_BLUE, "#A8B4C5", TAB_BLUE)
            self.lbl.config(font=(self.base_font[0], self.base_font[1], "normal"))


# --- Main Application --------------------------------------------------------
class MeterReaderApp(tb.Window if tb else tk.Tk):
    def __init__(self):
        if tb:
            super().__init__(themename="cosmo")
        else:
            super().__init__()
        self.update_idletasks()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self._screen_width = screen_width
        self._screen_height = screen_height

        self.title("Water Meter Reader")
        self.attributes("-fullscreen", True)
        self.geometry(f"{screen_width}x{screen_height}+0+0")
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))
        self.configure(bg=BG_COLOR)
        self.resizable(False, False)
        self._touch_font_base = 13 if self._screen_height >= 900 else 12
        self._content_max_width = min(max(420, int(self._screen_width * 0.95)), 560)
        self._content_max_height = max(520, int(self._screen_height - 8))

        self._current_page = "meter_entry"
        self._current_zone = tk.StringVar(value="")
        self._shake_after_ids = []
        self._progress_anim_fraction = 0.0
        self._progress_anim_id = None
        self._keyboard_target = None
        self._keyboard_mode = "alpha"
        self._keyboard_caps = False
        self._keyboard_hide_after_id = None
        self._sync_dal = None
        self._sync_state = "Offline"
        self._sync_pending_count = 0
        self._auto_pull_enabled = tk.BooleanVar(value=True)
        self._auto_push_enabled = tk.BooleanVar(value=True)
        self._auto_pull_interval_sec = tk.IntVar(value=60)
        self._auto_pull_after_id = None
        self._search_unread_only = tk.BooleanVar(value=True)

        # Currently loaded consumer from DB (None until a search is done)
        self._current_consumer = None
        # Cache zone stats from DB (loaded during startup sequence)
        self._zones_data = {}
        # Autocomplete state
        self._autocomplete_popup = None
        self._autocomplete_results = []
        self._zone_dropdown_popup = None

        # Current logged-in user
        self._current_user = None

        # Last receipt data for reprint workflow
        self._last_receipt_data = self._receipt_entry_to_payload(get_latest_receipt_print())
        self._loading_frame = None

        # Direct startup (no splash/loading gate).
        try:
            init_db()
            seed_default_users()  # Ensure default users exist
            self._zones_data = get_zone_stats()
            self._ensure_current_zone()
            self._build_ui()
            if hasattr(self, "login_screen"):
                self.login_screen.set_loading_status("Checking sync services...", "Please wait")
            self._init_handheld_sync()
            self._hydrate_local_consumers_from_sync()
            self._refresh_zone_stats()
            self._schedule_auto_pull()
            if hasattr(self, "login_screen"):
                sync_text = "Ready (Online)" if self._sync_state == "Online" else "Ready (Offline)"
                self.login_screen.set_loading_status(sync_text, "You can login now")
                self.after(1400, self.login_screen.hide_loading_status)
            self._start_system_status_updates()
            self.bind_all("<Button-1>", self._on_global_pointer_down, add="+")
        except Exception as exc:
            messagebox.showerror("Startup Error", f"Failed to initialize app:\n\n{exc}")

    def _hydrate_local_consumers_from_sync(self):
        """
        Pull assigned consumers from sync layer (online Supabase or local sync cache)
        and mirror them to local SQLite so UI always reads from fresh local data.
        """
        if not self._sync_dal:
            return 0
        try:
            consumers = self._sync_dal.loadAssignedConsumers(None)
            count = replace_consumers_from_sync(consumers)
            if hasattr(self, "login_screen"):
                self.login_screen.set_loading_status(
                    "Loading consumer dataset...",
                    f"{count} records ready",
                )
            self._last_pull_count = len(consumers)
            self._last_mirrored_count = count
            if hasattr(self, "_pull_mirror_label"):
                self._pull_mirror_label.config(
                    text=f"Last pull mirrored: {count} records (pulled {len(consumers)})"
                )
            return count
        except Exception as exc:
            print(f"Consumer hydration skipped: {exc}")
            self._last_pull_count = 0
            self._last_mirrored_count = 0
            if hasattr(self, "_pull_mirror_label"):
                self._pull_mirror_label.config(text="Last pull mirrored: failed")
            return 0

    def _schedule_auto_pull(self):
        if self._auto_pull_after_id:
            try:
                self.after_cancel(self._auto_pull_after_id)
            except Exception:
                pass
            self._auto_pull_after_id = None
        interval = max(15, int(self._auto_pull_interval_sec.get() or 60))
        self._auto_pull_after_id = self.after(interval * 1000, self._run_auto_pull_tick)

    def _run_auto_pull_tick(self):
        self._auto_pull_after_id = None
        if not self._auto_pull_enabled.get():
            self._schedule_auto_pull()
            return
        if not self._sync_dal:
            self._schedule_auto_pull()
            return

        def _task():
            try:
                online = self._sync_dal.is_online()
                mirrored = self._hydrate_local_consumers_from_sync()
                self.after(0, self._refresh_zone_stats)
                if online:
                    self.after(0, lambda count=mirrored: self._refresh_sync_status_ui(f"auto-pull complete ({count} mirrored)"))
                else:
                    self.after(0, lambda count=mirrored: self._refresh_sync_status_ui(f"offline, fallback pull ({count} mirrored)"))
            except Exception as exc:
                self.after(0, lambda: self._refresh_sync_status_ui(f"auto-pull failed: {exc}"))
            finally:
                self.after(0, self._schedule_auto_pull)

        threading.Thread(target=_task, daemon=True).start()

    def _ensure_current_zone(self):
        """Ensure selected zone is from live DB data, not a hardcoded fallback."""
        current = self._current_zone.get().strip() if hasattr(self, "_current_zone") else ""
        zone_names = []
        try:
            zone_names = list(self._zones_data.keys()) if isinstance(self._zones_data, dict) else []
            if not zone_names:
                zone_names = get_all_zone_names()
        except Exception:
            zone_names = []
        if zone_names and (not current or current not in zone_names):
            self._current_zone.set(zone_names[0])

    def _start_system_status_updates(self):
        self._update_system_status()
        self.after(15000, self._start_system_status_updates)

    def _update_system_status(self):
        """Update status bar with real connectivity, battery, and signal when available."""
        online = self._is_internet_reachable()
        battery = self._read_battery_level()
        signal = self._read_signal_strength(online)
        self.status_bar.set_signal(signal)
        if battery is not None:
            self.status_bar.set_battery(battery)

    @staticmethod
    def _is_internet_reachable(timeout_sec: float = 2.0) -> bool:
        try:
            with socket.create_connection(("1.1.1.1", 53), timeout=timeout_sec):
                return True
        except OSError:
            return False

    @staticmethod
    def _read_battery_level() -> int | None:
        # Raspberry Pi HATs and Linux battery devices expose capacity via /sys.
        try:
            power_supply_dir = "/sys/class/power_supply"
            if os.path.isdir(power_supply_dir):
                for name in os.listdir(power_supply_dir):
                    cap_path = os.path.join(power_supply_dir, name, "capacity")
                    if os.path.exists(cap_path):
                        with open(cap_path, "r", encoding="utf-8") as f:
                            value = int(f.read().strip())
                        return max(0, min(100, value))
        except Exception:
            pass
        return None

    @staticmethod
    def _read_signal_strength(online: bool) -> int:
        # On Linux, map Wi-Fi link quality to 0-4 bars when available.
        if not online:
            return 0
        if platform.system() != "Linux":
            return 4
        try:
            proc = subprocess.run(
                ["cat", "/proc/net/wireless"],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            lines = [ln.strip() for ln in proc.stdout.splitlines() if ":" in ln]
            if not lines:
                return 4
            # Example: wlan0: 0000 54. -56. -256 ...
            parts = lines[0].replace(":", " ").split()
            if len(parts) >= 3:
                quality = float(parts[2].strip("."))
                # Linux wireless quality is usually out of 70
                pct = max(0.0, min(1.0, quality / 70.0))
                if pct >= 0.8:
                    return 4
                if pct >= 0.6:
                    return 3
                if pct >= 0.35:
                    return 2
                return 1
        except Exception:
            pass
        return 4

    def _build_ui(self):
        self._configure_global_ui_styles()
        # -- Status Bar (Phone-style) -------------------------------------
        self.status_bar = StatusBar(self, height=28)
        self.status_bar.pack(fill="x")

        # -- Main Container -----------------------------------------------
        self.main_container = tk.Frame(self, bg=BG_COLOR)
        self.main_container.pack(fill="both", expand=True)
        self.main_container.bind("<Configure>", self._on_main_container_resize)

        # Centered content viewport for portrait touchscreens.
        self.content_viewport = tk.Frame(self.main_container, bg=BG_COLOR)
        self.content_viewport.place(relx=0.5, rely=0.5, anchor="center")
        self.content_viewport.grid_rowconfigure(0, weight=1)
        self.content_viewport.grid_columnconfigure(0, weight=1)
        self._update_content_viewport()

        # -- Login Screen (shown initially) -------------------------------
        self.login_screen = LoginScreen(self.content_viewport, self._on_login_success)
        self.login_screen.grid(row=0, column=0, sticky="nsew")

        # -- App Content (hidden until login) -----------------------------
        self.app_content = tk.Frame(self.content_viewport, bg=BG_COLOR)
        self.app_content.grid(row=0, column=0, sticky="nsew")
        self.app_content.grid_remove()

        self.keyboard_panel = tk.Frame(self.content_viewport, bg=TAB_DARK, bd=1, relief="flat")
        self.keyboard_panel.grid(row=1, column=0, sticky="ew")
        self.keyboard_panel.grid_remove()

        self._build_app_content()
        self._build_in_app_keyboard()
        self.bind_keyboard_to_entries(self.login_screen)
        self.bind_keyboard_to_entries(self.app_content)
        self._refresh_sync_status_ui()

    def _configure_global_ui_styles(self):
        """Normalize ttk dropdown/list styles so text matches app typography."""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        combo_font = (FONT_FAMILY, self._touch_font_base, "bold")
        style.configure(
            "Figma.TCombobox",
            fieldbackground=INPUT_BG,
            background=WHITE,
            foreground=DARK_TEXT,
            bordercolor=INPUT_BORDER,
            arrowcolor=MID_TEXT,
            relief="flat",
            padding=8,
            font=combo_font,
        )
        style.map(
            "Figma.TCombobox",
            fieldbackground=[("readonly", INPUT_BG)],
            foreground=[("readonly", DARK_TEXT)],
            bordercolor=[("focus", INPUT_FOCUS)],
        )
        self.option_add("*TCombobox*Listbox.font", f"{FONT_FAMILY} {self._touch_font_base}")
        self.option_add("*TCombobox*Listbox.background", WHITE)
        self.option_add("*TCombobox*Listbox.foreground", DARK_TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", PRIMARY_BLUE)
        self.option_add("*TCombobox*Listbox.selectForeground", WHITE)

    def _init_handheld_sync(self):
        """Initialize optional handheld sync layer from environment configuration."""
        if HandheldSyncDataAccess is None or SyncConfig is None:
            self._sync_state = "Sync Failed"
            self._refresh_sync_status_ui("sync module unavailable")
            return
        try:
            cfg = SyncConfig.from_env(fail_fast=False)
            if not cfg.sync_enabled:
                self._sync_state = "Offline"
                self._refresh_sync_status_ui("sync disabled")
                return
            self._sync_dal = HandheldSyncDataAccess.from_env(fail_fast=True)
            self._sync_dal.start_sync_worker(interval_seconds=20)
            self._sync_state = "Online" if self._sync_dal.is_online() else "Offline"
            self._sync_pending_count = len(self._sync_dal.listPendingSyncReadings())
            self._refresh_sync_status_ui()
        except Exception as exc:
            self._sync_dal = None
            self._sync_state = "Sync Failed"
            self._refresh_sync_status_ui(str(exc))

    def _refresh_sync_status_ui(self, detail: str = ""):
        pending = 0
        save_target = "Local SQLite only"
        backup_state = "Not configured"
        last_sync = "Never"
        if self._sync_dal:
            try:
                snap = self._sync_dal.get_sync_snapshot()
                pending = int(snap.get("pending_count", 0))
                self._sync_state = str(snap.get("status", self._sync_state))
                save_target = str(snap.get("save_target", save_target))
                backup_state = str(snap.get("backup_state", backup_state))
                if snap.get("last_sync_time"):
                    last_sync = str(snap.get("last_sync_time"))
            except Exception:
                self._sync_state = "Sync Failed"
                save_target = "Unavailable (sync error)"
                backup_state = "Unknown"
        self._sync_pending_count = pending

        if self._sync_state == "Online" and pending > 0:
            status_text = "Pending Sync"
            status_color = WARNING_TEXT
        elif self._sync_state == "Online":
            status_text = "Online"
            status_color = VALID_TEXT
        elif self._sync_state == "Sync Failed":
            status_text = "Sync Failed"
            status_color = INVALID_TEXT
        else:
            status_text = "Offline"
            status_color = MID_TEXT

        if hasattr(self, "_sync_status_label"):
            self._sync_status_label.config(text=f"Sync: {status_text}", fg=status_color)
        if hasattr(self, "_settings_sync_status"):
            self._settings_sync_status.config(text=f"Sync: {status_text}", fg=status_color)
        if hasattr(self, "_sync_pending_label"):
            self._sync_pending_label.config(text=f"Pending: {pending}")
        if hasattr(self, "_settings_pending_label"):
            self._settings_pending_label.config(text=f"Pending: {pending}")
        if hasattr(self, "_sync_target_label"):
            self._sync_target_label.config(text=f"Save Target: {save_target}")
        if hasattr(self, "_sync_backup_label"):
            self._sync_backup_label.config(text=f"Backup: {backup_state}")
        if hasattr(self, "_sync_last_label"):
            self._sync_last_label.config(text=f"Last Sync: {last_sync}")
        if detail and hasattr(self, "_sync_pending_label"):
            self._sync_pending_label.config(text=f"Pending: {pending} ({detail})")

    def _on_main_container_resize(self, event=None):
        self._update_content_viewport()

    def _update_content_viewport(self):
        """Keep app content centered while adapting to the current screen shape."""
        available_w = max(1, self.main_container.winfo_width())
        available_h = max(1, self.main_container.winfo_height())
        # Use full screen width so top/header bars reach both screen edges.
        viewport_w = available_w
        viewport_h = min(self._content_max_height, available_h)
        self.content_viewport.place_configure(width=viewport_w, height=viewport_h)

    def _is_text_input_widget(self, widget):
        if widget is None:
            return False
        return isinstance(widget, (tk.Entry, ttk.Entry))

    def _is_widget_in_keyboard_panel(self, widget):
        cur = widget
        while cur is not None:
            if cur == self.keyboard_panel:
                return True
            cur = getattr(cur, "master", None)
        return False

    def _schedule_keyboard_hide(self):
        if self._keyboard_hide_after_id:
            self.after_cancel(self._keyboard_hide_after_id)
        self._keyboard_hide_after_id = self.after(120, self._hide_keyboard_if_no_text_focus)

    def _hide_keyboard_if_no_text_focus(self):
        self._keyboard_hide_after_id = None
        try:
            focused = self.focus_get()
        except KeyError:
            # Tk can briefly report internal transient widgets (e.g. ttk combobox popdown)
            # that are not addressable via nametowidget; treat as non-text focus.
            focused = None
        except Exception:
            focused = None
        if self._is_widget_in_keyboard_panel(focused):
            return
        if not self._is_text_input_widget(focused):
            self.hide_keyboard()

    def _build_in_app_keyboard(self):
        self.keyboard_panel.configure(bg="#1C2434")
        self._keyboard_content = tk.Frame(self.keyboard_panel, bg="#1C2434")
        self._keyboard_content.pack(fill="both", expand=True, padx=14, pady=12)
        self._keyboard_mode = getattr(self, "_keyboard_mode", "alpha")
        self._keyboard_caps = getattr(self, "_keyboard_caps", False)
        from tkinter import font as tkfont
        self._key_font = tkfont.Font(
            family=FONT_FAMILY,
            size=getattr(self, "_touch_font_base", 13),
            weight="bold",
        )

    def _toggle_keyboard_mode(self):
        self._keyboard_mode = "numeric" if self._keyboard_mode != "numeric" else "alpha"
        self._render_keyboard()

    def _toggle_keyboard_caps(self):
        self._keyboard_caps = not self._keyboard_caps
        self._render_keyboard()

    def _render_keyboard(self):
        for child in self._keyboard_content.winfo_children():
            child.destroy()

        if self._keyboard_mode == "numeric":
            rows = ["123", "456", "789"]
        else:
            rows = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]

        # Use grid() + column weights so keys always divide the row width evenly,
        # preventing overflow on long rows like "qwertyuiop" (10 keys).
        for row_idx, row_keys in enumerate(rows):
            row = tk.Frame(self._keyboard_content, bg="#1C2434")
            row.pack(fill="x", pady=4)
            col = 0

            if self._keyboard_mode != "numeric" and row_idx == 2:
                RoundedKey(
                    row,
                    "⇧",
                    command=self._toggle_keyboard_caps,
                    bg="#334360" if self._keyboard_caps else "#2B3550",
                    hover="#354766", press="#41547E",
                    fg="#FFFFFF" if self._keyboard_caps else "#66C6FF", font=self._key_font,
                ).grid(row=0, column=col, sticky="nsew", padx=4)
                row.grid_columnconfigure(col, weight=15)
                col += 1

            for key_char in row_keys:
                label = key_char.upper() if self._keyboard_caps else key_char
                RoundedKey(
                    row, label,
                    command=lambda c=label: self._insert_key(c),
                    bg="#253048", hover="#2E3B5C", press="#3A4A70",
                    fg=WHITE, font=self._key_font,
                ).grid(row=0, column=col, sticky="nsew", padx=4)
                row.grid_columnconfigure(col, weight=10)
                col += 1

            if self._keyboard_mode != "numeric" and row_idx == 2:
                RoundedKey(
                    row, "⌫",
                    command=self._backspace_key,
                    bg="#2B3550", hover="#8a3b3b", press="#a54848",
                    fg="#66C6FF", font=self._key_font,
                ).grid(row=0, column=col, sticky="nsew", padx=4)
                row.grid_columnconfigure(col, weight=15)

            row.grid_rowconfigure(0, weight=1)

        if self._keyboard_mode == "numeric":
            bottom_row = tk.Frame(self._keyboard_content, bg="#1C2434")
            bottom_row.pack(fill="x", pady=4)
            for idx, (label, cmd, is_num) in enumerate([
                ("ABC", self._toggle_keyboard_mode, False),
                ("0",   lambda: self._insert_key("0"), True),
                ("⌫",   self._backspace_key, False),
            ]):
                RoundedKey(
                    bottom_row, label, command=cmd,
                    bg="#253048" if is_num else "#2B3550",
                    hover="#2E3B5C" if is_num else "#354766",
                    press="#3A4A70" if is_num else "#41547E",
                    fg=WHITE if is_num else "#66C6FF",
                    font=self._key_font,
                ).grid(row=0, column=idx, sticky="nsew", padx=4)
                bottom_row.grid_columnconfigure(idx, weight=1)
            bottom_row.grid_rowconfigure(0, weight=1)

        if self._keyboard_mode != "numeric":
            action_row = tk.Frame(self._keyboard_content, bg="#1C2434")
            action_row.pack(fill="x", pady=(8, 0))
            RoundedKey(
                action_row, "123", command=self._toggle_keyboard_mode,
                bg="#2B3550", hover="#354766", press="#41547E",
                fg="#66C6FF", font=self._key_font, height=60,
            ).grid(row=0, column=0, sticky="nsew", padx=4)
            RoundedKey(
                action_row, "space", command=lambda: self._insert_key(" "),
                bg="#2B3550", hover="#354766", press="#41547E",
                fg="#66C6FF", font=self._key_font, height=60,
            ).grid(row=0, column=1, sticky="nsew", padx=4)
            action_row.grid_columnconfigure(0, weight=25)
            action_row.grid_columnconfigure(1, weight=75)
            action_row.grid_rowconfigure(0, weight=1)

    def _get_keyboard_target(self):
        focused = self.focus_get()
        if self._is_text_input_widget(focused):
            self._keyboard_target = focused
        return self._keyboard_target

    def _insert_key(self, value):
        target = self._get_keyboard_target()
        if target is None:
            return
        try:
            target.insert("insert", value)
        except Exception:
            pass
        target.focus_set()

    def _backspace_key(self):
        target = self._get_keyboard_target()
        if target is None:
            return
        try:
            idx = target.index("insert")
            if idx > 0:
                target.delete(idx - 1)
        except Exception:
            pass
        target.focus_set()

    def _clear_key(self):
        target = self._get_keyboard_target()
        if target is None:
            return
        try:
            target.delete(0, "end")
        except Exception:
            pass
        target.focus_set()

    def show_keyboard(self, widget=None):
        target = widget if self._is_text_input_widget(widget) else self.focus_get()
        if not self._is_text_input_widget(target):
            return
        self._keyboard_target = target
        mode = getattr(target, "_keyboard_mode", "alpha")
        if mode not in ("alpha", "numeric"):
            mode = "alpha"
        if mode != self._keyboard_mode or not self.keyboard_panel.winfo_ismapped():
            self._keyboard_mode = mode
            self._render_keyboard()
        self.keyboard_panel.grid()

    def hide_keyboard(self):
        """Hide in-app keyboard panel."""
        self.keyboard_panel.grid_remove()
        self._keyboard_target = None

    def bind_keyboard_to_entries(self, parent, default_mode="alpha"):
        """Bind keyboard show/hide behavior to all Entry widgets under parent."""
        if parent is None:
            return

        def _bind_entry(widget):
            if not hasattr(widget, "_keyboard_mode"):
                widget._keyboard_mode = default_mode
            # Show keyboard only on explicit touch/click, not passive focus changes.
            widget.bind("<Button-1>", lambda e, w=widget: self.show_keyboard(w), add="+")
            widget.bind("<Return>", lambda e: self._schedule_keyboard_hide(), add="+")
            widget.bind("<Escape>", lambda e: self.hide_keyboard(), add="+")
            widget.bind("<FocusOut>", lambda e: self._schedule_keyboard_hide(), add="+")

        for child in parent.winfo_children():
            if isinstance(child, RoundedEntry):
                _bind_entry(child.entry)
            elif self._is_text_input_widget(child):
                _bind_entry(child)
            self.bind_keyboard_to_entries(child, default_mode=default_mode)

    def _on_global_pointer_down(self, event):
        if self._is_widget_in_keyboard_panel(event.widget):
            return
        if not self._is_text_input_widget(event.widget):
            self.hide_keyboard()

    def _make_centered_body(self, parent, max_width=1180):
        """Create a responsive body that stays readable on wide displays."""
        host = tk.Frame(parent, bg=BG_COLOR)
        host.pack(fill="both", expand=True)
        body = tk.Frame(host, bg=BG_COLOR)
        body.place(relx=0.5, y=0, anchor="n", relheight=1)

        def _resize(event):
            side_margin = 20 if event.width < 720 else 48
            width = min(max_width, max(280, event.width - side_margin))
            body.place_configure(width=width)

        host.bind("<Configure>", _resize)
        return body

    def _make_scrollable_body(self, parent, max_width=1180):
        """Create a vertically scrollable body for longer touchscreen pages."""
        host = tk.Frame(parent, bg=BG_COLOR)
        host.pack(fill="both", expand=True)

        canvas = tk.Canvas(host, bg=BG_COLOR, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        body = tk.Frame(canvas, bg=BG_COLOR)
        window_id = canvas.create_window((0, 0), window=body, anchor="n")

        def _resize(event=None):
            canvas_width = max(1, canvas.winfo_width())
            side_margin = 20 if canvas_width < 720 else 48
            width = min(max_width, max(280, canvas_width - side_margin))
            canvas.itemconfigure(window_id, width=width)

        def _update_scrollregion(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_mousewheel(event):
            if event.delta:
                canvas.yview_scroll(int(-event.delta / 120), "units")

        def _bind_mousewheel(event=None):
            canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")

        def _unbind_mousewheel(event=None):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Configure>", _resize)
        body.bind("<Configure>", _update_scrollregion)
        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)
        _resize()
        return body

    @staticmethod
    def _section_title(parent, text, size=13):
        row = tk.Frame(parent, bg=parent["bg"])
        marker = tk.Frame(row, bg=PRIMARY_BLUE, width=4, height=19)
        marker.pack(side="left", padx=(0, 10))
        marker.pack_propagate(False)
        tk.Label(
            row,
            text=text,
            font=(FONT_FAMILY, size, "bold"),
            fg=DARK_TEXT,
            bg=parent["bg"],
        ).pack(side="left")
        return row

    def _build_app_content(self):
        """Build the main application content (shown after login)."""
        # -- Tab Navigation -----------------------------------------------
        tab_bar = tk.Frame(self.app_content, bg=TAB_DARK, height=64)
        tab_bar.pack(fill="x")
        tab_bar.pack_propagate(False)

        self.entry_tab_btn = ModernTabButton(
            tab_bar, text="Meter Entry", font=(FONT_FAMILY, self._touch_font_base + 1),
            command=lambda: self._switch_page("meter_entry"))
        self.entry_tab_btn.pack(side="left", fill="both", expand=True)

        self.progress_tab_btn = ModernTabButton(
            tab_bar, text="Progress", font=(FONT_FAMILY, self._touch_font_base + 1),
            command=lambda: self._switch_page("progress"))
        self.progress_tab_btn.pack(side="left", fill="both", expand=True)

        self.settings_tab_btn = ModernTabButton(
            tab_bar, text="Settings", font=(FONT_FAMILY, self._touch_font_base + 1),
            command=lambda: self._switch_page("settings"))
        self.settings_tab_btn.pack(side="left", fill="both", expand=True)

        # -- Pages Container ---------------------------------------------
        self.pages_container = tk.Frame(self.app_content, bg=BG_COLOR)
        self.pages_container.pack(fill="both", expand=True)

        self._build_meter_entry_page()
        self._build_progress_page()
        self._build_settings_page()
        self._switch_page("meter_entry")

    def _on_login_success(self, user: dict):
        """Handle successful login."""
        self._current_user = user
        self.hide_keyboard()

        # Store user info for profile menu

        # Switch to app content
        self.login_screen.grid_remove()
        self.app_content.grid()
        self.app_content.tkraise()
        self._refresh_zone_stats()

        # Show welcome message
        messagebox.showinfo("Welcome", f"Welcome, {user['name']}!\n\nID: {user['id']}")

    def _show_zone_dropdown(self):
        """Show a dropdown popup for selecting zones."""
        if self._zone_dropdown_popup and self._zone_dropdown_popup.winfo_exists():
            self._hide_zone_dropdown()
            return

        zones = get_all_zone_names()
        if not zones:
            return

        self._zone_dropdown_popup = tk.Toplevel(self)
        self._zone_dropdown_popup.overrideredirect(True)
        self._zone_dropdown_popup.configure(bg=BORDER_COLOR)
        self._zone_dropdown_popup.attributes("-topmost", True)

        label_x = self._active_zone_label.winfo_rootx()
        label_y = self._active_zone_label.winfo_rooty()
        label_height = self._active_zone_label.winfo_height()

        dropdown_frame = tk.Frame(self._zone_dropdown_popup, bg=WHITE, bd=1, relief="solid")
        dropdown_frame.pack(fill="both", expand=True)

        visible_rows = min(len(zones), 6)
        zone_list = tk.Listbox(
            dropdown_frame,
            height=visible_rows,
            font=(FONT_FAMILY, 11),
            bg=WHITE,
            fg=DARK_TEXT,
            selectbackground=PRIMARY_BLUE,
            selectforeground=WHITE,
            activestyle="none",
            relief="flat",
            bd=0,
            highlightthickness=0,
            exportselection=False,
            cursor="hand2",
        )
        zone_list.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)

        for zone in zones:
            zone_list.insert("end", zone)

        if len(zones) > visible_rows:
            scrollbar = ttk.Scrollbar(dropdown_frame, orient="vertical", command=zone_list.yview)
            scrollbar.pack(side="right", fill="y")
            zone_list.configure(yscrollcommand=scrollbar.set)

        current_zone = self._current_zone.get()
        if current_zone in zones:
            current_index = zones.index(current_zone)
            zone_list.selection_set(current_index)
            zone_list.activate(current_index)
            zone_list.see(current_index)

        def _choose_zone(event=None):
            selection = zone_list.curselection()
            if selection:
                self._select_zone(zones[selection[0]])

        def _wheel(event):
            if getattr(event, "delta", 0):
                zone_list.yview_scroll(-1 if event.delta > 0 else 1, "units")
            elif getattr(event, "num", None) == 4:
                zone_list.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                zone_list.yview_scroll(1, "units")
            return "break"

        zone_list.bind("<Double-Button-1>", _choose_zone)
        zone_list.bind("<Return>", _choose_zone)
        zone_list.bind("<Escape>", lambda e: self._hide_zone_dropdown())
        zone_list.bind("<MouseWheel>", _wheel)
        zone_list.bind("<Button-4>", _wheel)
        zone_list.bind("<Button-5>", _wheel)
        zone_list.bind("<ButtonRelease-1>", _choose_zone)

        dropdown_width = max(190, self._active_zone_label.winfo_width() + 36)
        self._zone_dropdown_popup.update_idletasks()
        dropdown_height = self._zone_dropdown_popup.winfo_reqheight()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        popup_x = min(label_x, screen_width - dropdown_width - 8)
        popup_y = label_y + label_height
        if popup_y + dropdown_height > screen_height - 8:
            popup_y = max(8, label_y - dropdown_height)
        self._zone_dropdown_popup.geometry(
            f"{dropdown_width}x{dropdown_height}+{max(8, popup_x)}+{popup_y}"
        )

        self._zone_dropdown_popup.bind("<FocusOut>", lambda e: self.after(100, self._hide_zone_dropdown))
        zone_list.focus_set()
    
    def _hide_zone_dropdown(self):
        """Hide the zone dropdown popup."""
        if self._zone_dropdown_popup and self._zone_dropdown_popup.winfo_exists():
            self._zone_dropdown_popup.destroy()
        self._zone_dropdown_popup = None

    def _show_profile_menu(self, btn=None):
        """Show profile dropdown menu with user info and logout."""
        if hasattr(self, '_profile_menu_popup') and self._profile_menu_popup and self._profile_menu_popup.winfo_exists():
            self._hide_profile_menu()
            return
        
        # Use the clicked button or default to first one
        profile_btn = btn if btn else (self._profile_btn if hasattr(self, '_profile_btn') else self._profile_btn2)
        if not profile_btn:
            return
        
        # Create popup
        self._profile_menu_popup = tk.Toplevel(self)
        self._profile_menu_popup.overrideredirect(True)
        self._profile_menu_popup.configure(bg=BORDER_COLOR)
        
        # Position below profile button
        btn_x = profile_btn.winfo_rootx()
        btn_y = profile_btn.winfo_rooty()
        btn_height = profile_btn.winfo_height()
        
        # Create menu frame
        menu_frame = tk.Frame(self._profile_menu_popup, bg=BORDER_COLOR, bd=1)
        menu_frame.pack(fill="both", expand=True)
        
        # User info section
        if self._current_user:
            user_frame = tk.Frame(menu_frame, bg=BG_COLOR, padx=12, pady=10)
            user_frame.pack(fill="x", pady=(0, 1))
            
            tk.Label(user_frame, text=self._current_user['name'], 
                    font=(FONT_FAMILY, 11, "bold"), bg=BG_COLOR, fg=DARK_TEXT).pack(anchor="w")
            tk.Label(user_frame, text=f"ID: {self._current_user['id']}", 
                    font=(FONT_FAMILY, 9), bg=BG_COLOR, fg=MID_TEXT).pack(anchor="w")
        
        # Logout button
        logout_frame = tk.Frame(menu_frame, bg=WHITE, padx=12, pady=8)
        logout_frame.pack(fill="x")
        logout_frame.bind("<Enter>", lambda e: logout_frame.config(bg="#FFF8E1"))
        logout_frame.bind("<Leave>", lambda e: logout_frame.config(bg=WHITE))
        logout_frame.bind("<Button-1>", lambda e: self._logout_from_menu())
        
        logout_lbl = tk.Label(logout_frame, text="Logout", 
                             font=(FONT_FAMILY, 10, "bold"), bg=WHITE, fg="#E53935", cursor="hand2")
        logout_lbl.pack(anchor="w")
        logout_lbl.bind("<Enter>", lambda e: logout_frame.config(bg="#FFF8E1"))
        logout_lbl.bind("<Leave>", lambda e: logout_frame.config(bg=WHITE))
        logout_lbl.bind("<Button-1>", lambda e: self._logout_from_menu())
        
        # Set geometry (height increased to fit both user info and logout)
        self._profile_menu_popup.geometry(f"160x110+{btn_x-120}+{btn_y + btn_height}")
        
        # Close when clicking outside
        self._profile_menu_popup.bind("<FocusOut>", lambda e: self._hide_profile_menu())
        self._profile_menu_popup.focus_set()
    
    def _hide_profile_menu(self):
        """Hide the profile menu popup."""
        if hasattr(self, '_profile_menu_popup') and self._profile_menu_popup and self._profile_menu_popup.winfo_exists():
            self._profile_menu_popup.destroy()
        self._profile_menu_popup = None
    
    def _logout_from_menu(self):
        """Logout from the profile menu."""
        self._hide_profile_menu()
        self._logout()
    
    def _on_zone_btn_hover(self, is_hover: bool):
        """Handle hover effect on zone button."""
        color = ACCENT_BLUE if is_hover else PRIMARY_BLUE
        self._zone_btn_frame.config(bg=color)
        self._active_zone_label.config(bg=color)
    
    def _select_zone(self, zone_name: str):
        """Select a new zone and update the UI."""
        self._hide_zone_dropdown()

        if zone_name == self._current_zone.get():
            return

        # Update current zone
        self._current_zone.set(zone_name)
        self._active_zone_label.config(text=zone_name)

        # Clear current consumer data since consumers are zone-specific
        self._current_consumer = None
        self.search_var.set("")

        # Clear detail labels
        for label in ["Account No.", "Name", "Previous"]:
            self._detail_labels[label].config(text="-")

        # Reset consumption display
        self._cons_title_label.config(text="-", fg=LIGHT_TEXT)
        self._cons_message_label.config(text="-", fg=LIGHT_TEXT)
        self._validation_icon_label.config(text="")
        self.reading_input.entry.delete(0, "end")
        self.exception_var.set("None")
        self.reading_input.clear_border_override()
    
    def _logout(self):
        """Handle logout."""
        if messagebox.askyesno("Logout", "Are you sure you want to logout?"):
            self._current_user = None
            self.hide_keyboard()
            self.login_screen.clear()
            self.app_content.grid_remove()
            self.login_screen.grid()
            self.login_screen.tkraise()

    def _switch_page(self, page_name):
        self.hide_keyboard()
        self._current_page = page_name

        if page_name == "meter_entry":
            self.entry_tab_btn.set_active(True)
            self.progress_tab_btn.set_active(False)
            self.settings_tab_btn.set_active(False)
            self.meter_entry_frame.tkraise()
        elif page_name == "progress":
            self.entry_tab_btn.set_active(False)
            self.progress_tab_btn.set_active(True)
            self.settings_tab_btn.set_active(False)
            self.progress_frame.tkraise()
            self._animate_progress_bar()
            # Hide autocomplete when switching to progress tab
            self._hide_autocomplete()
        else:
            self.entry_tab_btn.set_active(False)
            self.progress_tab_btn.set_active(False)
            self.settings_tab_btn.set_active(True)
            self.settings_frame.tkraise()

    # ----------------------------------------------------------------------
    #  METER ENTRY PAGE (Non-Scrolling, Compact Grouped Card)
    # ----------------------------------------------------------------------
    def _build_meter_entry_page(self):
        self.meter_entry_frame = tk.Frame(self.pages_container, bg=BG_COLOR)
        self.pages_container.grid_rowconfigure(0, weight=1)
        self.pages_container.grid_columnconfigure(0, weight=1)
        self.meter_entry_frame.grid(row=0, column=0, sticky="nsew")

        # -- Fixed Header -------------------------------------------------
        header_bg = tk.Frame(self.meter_entry_frame, bg=HEADER_BLUE, height=56)
        header_bg.pack(fill="x")
        header_bg.pack_propagate(False)

        header_content = tk.Frame(header_bg, bg=HEADER_BLUE)
        header_content.pack(fill="both", expand=True, padx=24, pady=7)

        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "images", "SLR logo 1.png")
        if os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path)
                logo_img.thumbnail((34, 34), Image.Resampling.LANCZOS)
                self.logo_photo = ImageTk.PhotoImage(logo_img)
                tk.Label(header_content, image=self.logo_photo, bg=HEADER_BLUE).pack(side="left", padx=(0, 6))
            except Exception:
                pass

        tk.Label(header_content, text="Water Meter Reading System", font=(FONT_FAMILY, 14, "bold"), bg=HEADER_BLUE, fg=WHITE).pack(side="left", anchor="w")

        # Profile icon in header
        self._profile_btn = tk.Label(header_content, text="User", font=(FONT_FAMILY, 11, "bold"),
                                     bg=HEADER_BLUE, fg=WHITE, cursor="hand2")
        self._profile_btn.pack(side="right")
        self._profile_btn.bind("<Button-1>", lambda e, b=self._profile_btn: self._show_profile_menu(b))

        # -- Main Content Container ---------------------------------------
        main = self._make_scrollable_body(self.meter_entry_frame, max_width=1120)

        px = 0

        # -- Search Section -----------------------------------------------
        search_section = tk.Frame(main, bg=BG_COLOR)
        search_section.pack(fill="x", padx=px, pady=(18, 8))

        search_header = tk.Frame(search_section, bg=BG_COLOR)
        search_header.pack(fill="x", pady=0)

        tk.Label(search_header, text="Search by Meter No.", font=(FONT_FAMILY, 13, "bold"), fg=DARK_TEXT, bg=BG_COLOR).pack(side="left")

        # Zone selector button (styled like a button)
        self._zone_btn_frame = tk.Frame(search_header, bg=PRIMARY_BLUE, padx=2, pady=2)
        self._zone_btn_frame.pack(side="right")
        
        self._active_zone_label = tk.Label(self._zone_btn_frame, text=self._current_zone.get(),
                                           font=(FONT_FAMILY, 12, "bold"),
                                           fg=WHITE, bg=PRIMARY_BLUE,
                                           padx=16, pady=7,
                                           cursor="hand2")
        self._active_zone_label.pack()
        
        # Bind click to both frame and label
        self._zone_btn_frame.bind("<Button-1>", lambda e: self._show_zone_dropdown())
        self._active_zone_label.bind("<Button-1>", lambda e: self._show_zone_dropdown())
        
        # Hover effects
        self._zone_btn_frame.bind("<Enter>", lambda e: self._on_zone_btn_hover(True))
        self._zone_btn_frame.bind("<Leave>", lambda e: self._on_zone_btn_hover(False))
        self._active_zone_label.bind("<Enter>", lambda e: self._on_zone_btn_hover(True))
        self._active_zone_label.bind("<Leave>", lambda e: self._on_zone_btn_hover(False))

        self.search_var = tk.StringVar()
        self.search_input = RoundedEntry(search_section, placeholder="Type 001, 002...", height=54, radius=8, font=(FONT_FAMILY, self._touch_font_base + 1), textvariable=self.search_var)
        self.search_input.pack(fill="x", pady=(8, 0))
        self.search_input.entry.bind("<Return>", self._on_search)
        self.search_input.entry.bind("<KeyRelease>", self._on_search_key)
        self.search_input.entry.bind("<FocusOut>", self._schedule_hide_autocomplete)



        self._sync_target_label = None
        self._sync_backup_label = None
        self._sync_last_label = None
        self._sync_log_btn = None

        # -- Grouped Detail Card ------------------------------------------
        self.group_card = GroupCard(main, radius=8, bg_color=WHITE, padding=20)
        self.group_card.pack(fill="x", padx=px, pady=(0, 10))
        card = self.group_card.inner_frame

        # -- Consumer Details Section -------------------------------------
        details_section = tk.Frame(card, bg=WHITE)
        details_section.pack(fill="x", pady=(0, 0))

        self._section_title(details_section, "Consumer Details").pack(anchor="w", pady=(0, 10))

        self._detail_labels = {}
        for label in ["Account No.", "Name", "Previous"]:
            row = tk.Frame(details_section, bg=WHITE)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE).pack(side="left")
            val_lbl = tk.Label(row, text="-", font=(FONT_FAMILY, 11, "bold"), fg=DARK_TEXT, bg=WHITE)
            val_lbl.pack(side="right")
            self._detail_labels[label] = val_lbl

        # Compact separator
        tk.Frame(card, height=1, bg=BORDER_COLOR).pack(fill="x", pady=12)

        # -- Present Reading Section --------------------------------------
        ri = tk.Frame(card, bg=WHITE)
        ri.pack(fill="x", pady=0)

        self._section_title(ri, "Present Reading", size=12).pack(anchor="w", pady=(0, 8))

        vcmd = (self.register(self._validate_numeric), "%P")

        self.present_var = tk.StringVar()
        self.reading_input = RoundedEntry(
            ri, placeholder="Enter current reading...",
            height=54, radius=8, bg=INPUT_BG,
            font=(FONT_FAMILY, 16, "bold"), justify="left",
            textvariable=self.present_var)
        self.reading_input.pack(fill="x", pady=0)
        self.reading_input.set_validate(vcmd)
        self.reading_input.entry._keyboard_mode = "numeric"

        self._validation_frame = tk.Frame(ri, bg=WHITE)
        self._validation_frame.pack(fill="x")
        self._validation_icon_label = tk.Label(
            self._validation_frame, text="", font=(FONT_FAMILY, 9),
            fg=INVALID_TEXT, bg=WHITE)
        self._validation_icon_label.pack(side="left", anchor="w")

        cons_row = tk.Frame(ri, bg=WHITE)
        cons_row.pack(fill="x", pady=(8, 0))

        tk.Label(cons_row, text="Consumption", font=(FONT_FAMILY, 11, "bold"), fg=DARK_TEXT, bg=WHITE).pack(side="left")

        cons_right = tk.Frame(cons_row, bg=WHITE)
        cons_right.pack(side="right")

        self._cons_title_label = tk.Label(cons_right, text="-", font=(FONT_FAMILY, 14, "bold"), fg=LIGHT_TEXT, bg=WHITE)
        self._cons_title_label.pack(anchor="e")

        self._cons_message_label = tk.Label(cons_right, text="-", font=(FONT_FAMILY, 9), fg=LIGHT_TEXT, bg=WHITE)
        self._cons_message_label.pack(anchor="e")

        self.present_var.trace_add("write", self._update_consumption)

        tk.Frame(card, height=1, bg=BORDER_COLOR).pack(fill="x", pady=12)

        # -- Exception Section --------------------------------------------
        ei = tk.Frame(card, bg=WHITE)
        ei.pack(fill="x", pady=0)

        tk.Label(ei, text="Exception", font=(FONT_FAMILY, 11, "bold"), fg=DARK_TEXT, bg=WHITE).pack(anchor="w", pady=(0, 5))

        self.exception_var = tk.StringVar(value="None")

        style = ttk.Style()
        style.configure(
            "Figma.TCombobox",
            fieldbackground=INPUT_BG,
            background=WHITE,
            foreground=DARK_TEXT,
            bordercolor=INPUT_BORDER,
            arrowcolor=MID_TEXT,
            relief="flat",
            padding=8,
            font=(FONT_FAMILY, self._touch_font_base, "bold"),
        )
        style.map(
            "Figma.TCombobox",
            fieldbackground=[("readonly", INPUT_BG)],
            foreground=[("readonly", DARK_TEXT)],
            bordercolor=[("focus", INPUT_FOCUS)],
        )

        ttk.Combobox(ei, textvariable=self.exception_var,
                     values=["None", "Stuck Meter", "Leaking", "No Access", "Broken Seal"],
                     state="readonly", font=(FONT_FAMILY, self._touch_font_base, "bold"), style="Figma.TCombobox"
                     ).pack(fill="x", ipady=8, pady=(0, 4))

        # -- PRINT Button -------------------------------------------------
        btn_wrapper = tk.Frame(main, bg=BG_COLOR)
        btn_wrapper.pack(fill="x", padx=px, pady=(2, 6))

        self.print_btn = RoundedButton(
            btn_wrapper, text="PRINT", command=self._on_print,
            radius=8, bg_color=TAB_DARK, fg_color=WHITE,
            font=(FONT_FAMILY, 15, "bold"), shadow_color="#CBD5E1", height=58)
        self.print_btn.text = "PRINT"
        self.print_btn.pack(fill="x", pady=(0, 8))

        # -- Reprint Button -----------------------------------------------
        reprint_wrapper = tk.Frame(main, bg=BG_COLOR)
        reprint_wrapper.pack(fill="x", padx=px, pady=(0, 4))

        self.reprint_btn = tk.Button(
            reprint_wrapper, text="Reprint Last Receipt",
            font=(FONT_FAMILY, self._touch_font_base, "bold"),
            bg="#E3F2FD", fg=PRIMARY_BLUE,
            activebackground="#BBDEFB", activeforeground=PRIMARY_BLUE,
            relief="flat", bd=0, cursor="hand2",
            highlightthickness=0, command=self._show_reprint_dialog)
        self.reprint_btn.pack(fill="x", ipady=13)

        self.reprint_btn.bind("<Enter>", lambda e: e.widget.config(bg="#BBDEFB"))
        self.reprint_btn.bind("<Leave>", lambda e: e.widget.config(bg="#E3F2FD"))

        # -- Paper Status Controls (for demo/testing) ---------------------
        paper_control = tk.Frame(main, bg=BG_COLOR)
        paper_control.pack(fill="x", padx=px, pady=(4, 0))

        tk.Label(paper_control, text="Paper Status (Test):", font=(FONT_FAMILY, 10),
                 bg=BG_COLOR, fg=MID_TEXT).pack(side="left")

        paper_states = [
            ("OK", "ok", PAPER_OK),
            ("Low", "low", PAPER_LOW),
            ("Out", "out", PAPER_OUT),
            ("Jam", "jam", PAPER_JAM),
        ]

        for label, state, color in paper_states:
            btn = tk.Label(paper_control, text=label, font=(FONT_FAMILY, 10, "bold"),
                          bg=BG_COLOR, fg=color, cursor="hand2", padx=8, pady=6)
            btn.pack(side="right")
            btn.bind("<Button-1>", lambda e, s=state: self.status_bar.set_paper_status(s))


    # ----------------------------------------------------------------------
    #  PROGRESS PAGE (Non-Scrolling, Compact & Large Texts)
    # ----------------------------------------------------------------------
    def _build_progress_page(self):
        self.progress_frame = tk.Frame(self.pages_container, bg=BG_COLOR)
        self.progress_frame.grid(row=0, column=0, sticky="nsew")

        header_bg = tk.Frame(self.progress_frame, bg=HEADER_BLUE, height=56)
        header_bg.pack(fill="x")
        header_bg.pack_propagate(False)

        header_content = tk.Frame(header_bg, bg=HEADER_BLUE)
        header_content.pack(fill="both", expand=True, padx=24, pady=7)

        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "images", "SLR logo 1.png")
        if os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path)
                logo_img.thumbnail((34, 34), Image.Resampling.LANCZOS)
                self._progress_logo = ImageTk.PhotoImage(logo_img)
                tk.Label(header_content, image=self._progress_logo, bg=HEADER_BLUE).pack(side="left", padx=(0, 6))
            except Exception:
                pass

        tk.Label(header_content, text="Water Meter Reading System", font=(FONT_FAMILY, 14, "bold"), bg=HEADER_BLUE, fg=WHITE).pack(side="left", anchor="w")

        # Profile icon in header
        self._profile_btn2 = tk.Label(header_content, text="User", font=(FONT_FAMILY, 11, "bold"),
                                      bg=HEADER_BLUE, fg=WHITE, cursor="hand2")
        self._profile_btn2.pack(side="right")
        self._profile_btn2.bind("<Button-1>", lambda e, b=self._profile_btn2: self._show_profile_menu(b))

        # -- Main Content Container (wrapped in _progress_content for showing/hiding) ------------------------
        self._progress_content = tk.Frame(self.progress_frame, bg=BG_COLOR)
        self._progress_content.pack(fill="both", expand=True)
        
        main = self._make_scrollable_body(self._progress_content, max_width=1240)

        px = 0

        # -- Assigned Zone Section ----------------------------------------
        zi = tk.Frame(main, bg=BG_COLOR)
        zi.pack(fill="x", padx=px, pady=(24, 10))

        tk.Label(zi, text="Assigned Zone", font=(FONT_FAMILY, 13, "bold"), fg=DARK_TEXT, bg=BG_COLOR).pack(anchor="w", pady=(0, 10))

        self._zone_combo = ttk.Combobox(zi, textvariable=self._current_zone,
                                   values=get_all_zone_names(),
                                   state="readonly", font=(FONT_FAMILY, 12, "bold"),
                                   style="Figma.TCombobox")
        self._zone_combo.pack(fill="x", ipady=9)
        self._zone_combo.bind("<<ComboboxSelected>>", self._on_zone_change)

        # -- Today's Progress Card (Blue) ---------------------------------
        self._progress_canvas = tk.Canvas(main, bg=BG_COLOR, highlightthickness=0, height=340)
        self._progress_canvas.pack(fill="x", padx=px, pady=(10, 8))

        # -- Zone Info Card (White) ---------------------------------------
        self._zone_info_canvas = tk.Canvas(main, bg=BG_COLOR, highlightthickness=0, height=160)
        self._zone_info_canvas.pack(fill="x", padx=px, pady=(8, 22))

        self._zone_info_canvas.bind("<Configure>", self._redraw_zone_card)
        self._progress_canvas.bind("<Configure>", self._redraw_progress_card)

    def _build_settings_page(self):
        self.settings_frame = tk.Frame(self.pages_container, bg=BG_COLOR)
        self.settings_frame.grid(row=0, column=0, sticky="nsew")

        header_bg = tk.Frame(self.settings_frame, bg=PRIMARY_BLUE, height=68)
        header_bg.pack(fill="x")
        header_bg.pack_propagate(False)
        tk.Label(
            header_bg,
            text="Settings",
            font=(FONT_FAMILY, 16, "bold"),
            bg=PRIMARY_BLUE,
            fg=WHITE,
        ).pack(expand=True)

        main = self._make_scrollable_body(self.settings_frame, max_width=1160)

        def _settings_icon(parent, kind):
            icon = tk.Canvas(parent, width=58, height=58, bg=WHITE, highlightthickness=0)
            self._draw_rr(icon, 2, 2, 56, 56, 8, fill=PRIMARY_BLUE, outline="")
            if kind == "wifi":
                icon.create_arc(14, 15, 44, 43, start=35, extent=110, style="arc", outline=WHITE, width=3)
                icon.create_arc(19, 22, 39, 42, start=35, extent=110, style="arc", outline=WHITE, width=3)
                icon.create_oval(27, 38, 31, 42, fill=WHITE, outline=WHITE)
            else:
                icon.create_oval(17, 24, 31, 38, outline=WHITE, width=2)
                icon.create_oval(25, 17, 41, 37, outline=WHITE, width=2)
                icon.create_oval(34, 25, 46, 38, outline=WHITE, width=2)
                icon.create_line(18, 37, 44, 37, fill=WHITE, width=2)
                icon.create_line(31, 30, 31, 44, fill=WHITE, width=2)
                icon.create_line(27, 40, 31, 44, 35, 40, fill=WHITE, width=2)
            return icon

        card = GroupCard(main, radius=8, bg_color=WHITE, padding=24)
        card.pack(fill="x", pady=(22, 12))
        inner = card.inner_frame

        sync_header = tk.Frame(inner, bg=WHITE)
        sync_header.pack(fill="x")
        _settings_icon(sync_header, "sync").pack(side="left", padx=(0, 18))
        sync_heading = tk.Frame(sync_header, bg=WHITE)
        sync_heading.pack(side="left", fill="y")
        tk.Label(sync_heading, text="Sync Diagnostics", font=(FONT_FAMILY, 16, "bold"), fg=DARK_TEXT, bg=WHITE).pack(anchor="w", pady=(2, 0))
        self._settings_sync_status = tk.Label(sync_heading, text="Sync: Offline", font=(FONT_FAMILY, 11, "bold"), fg=MID_TEXT, bg=WHITE, anchor="w")
        self._settings_sync_status.pack(anchor="w", pady=(8, 0))

        sync_body = tk.Frame(inner, bg=WHITE)
        sync_body.pack(fill="x", pady=(20, 18))
        sync_body.grid_columnconfigure(0, weight=1, uniform="sync")
        sync_body.grid_columnconfigure(2, weight=1, uniform="sync")

        diagnostics = tk.Frame(sync_body, bg=WHITE)
        diagnostics.grid(row=0, column=0, sticky="nsew", padx=(0, 34))
        self._settings_pending_label = tk.Label(diagnostics, text="Pending: 0", font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE, anchor="w")
        self._settings_pending_label.pack(fill="x", pady=4)
        self._sync_target_label = tk.Label(diagnostics, text="Save Target: Local SQLite only", font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE, anchor="w")
        self._sync_target_label.pack(fill="x", pady=4)
        self._sync_backup_label = tk.Label(diagnostics, text="Backup: Not configured", font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE, anchor="w")
        self._sync_backup_label.pack(fill="x", pady=4)
        self._sync_last_label = tk.Label(diagnostics, text="Last Sync: Never", font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE, anchor="w")
        self._sync_last_label.pack(fill="x", pady=4)
        self._pull_mirror_label = tk.Label(diagnostics, text="Last pull mirrored: 0 records", font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE, anchor="w")
        self._pull_mirror_label.pack(fill="x", pady=4)

        separator = tk.Frame(sync_body, bg=BORDER_COLOR, width=1)
        separator.grid(row=0, column=1, sticky="ns")

        sync_cfg = tk.Frame(sync_body, bg=WHITE)
        sync_cfg.grid(row=0, column=2, sticky="nsew", padx=(34, 0))
        tk.Checkbutton(
            sync_cfg,
            text="Auto Pull from Main DB (online)",
            variable=self._auto_pull_enabled,
            bg=WHITE,
            fg=DARK_TEXT,
            activebackground=WHITE,
            activeforeground=DARK_TEXT,
            selectcolor=WHITE,
            font=(FONT_FAMILY, 10, "bold"),
            command=self._on_sync_config_changed,
            highlightthickness=0,
            bd=0,
        ).pack(anchor="w", pady=(0, 10))
        tk.Checkbutton(
            sync_cfg,
            text="Auto Push New Readings",
            variable=self._auto_push_enabled,
            bg=WHITE,
            fg=DARK_TEXT,
            activebackground=WHITE,
            activeforeground=DARK_TEXT,
            selectcolor=WHITE,
            font=(FONT_FAMILY, 10, "bold"),
            command=self._on_sync_config_changed,
            highlightthickness=0,
            bd=0,
        ).pack(anchor="w", pady=(0, 18))

        interval_row = tk.Frame(sync_cfg, bg=WHITE)
        interval_row.pack(fill="x")
        tk.Label(interval_row, text="Pull interval (sec):", font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE).pack(side="left")
        self._pull_interval_entry = tk.Entry(
            interval_row,
            textvariable=self._auto_pull_interval_sec,
            width=6,
            font=(FONT_FAMILY, 10, "bold"),
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightbackground=INPUT_BORDER,
            highlightcolor=INPUT_FOCUS,
        )
        self._pull_interval_entry.pack(side="left", padx=(12, 0), ipady=8)
        self._pull_interval_entry.bind("<FocusOut>", lambda e: self._on_sync_config_changed())
        self._pull_interval_entry.bind("<Return>", lambda e: self._on_sync_config_changed())

        sync_layout_state = {"mode": None}

        def _layout_sync_columns(event):
            mode = "stacked" if event.width < 720 else "columns"
            if sync_layout_state["mode"] == mode:
                return
            sync_layout_state["mode"] = mode
            diagnostics.grid_forget()
            separator.grid_forget()
            sync_cfg.grid_forget()
            if mode == "stacked":
                sync_body.grid_columnconfigure(0, weight=1)
                sync_body.grid_columnconfigure(1, weight=0)
                sync_body.grid_columnconfigure(2, weight=0)
                diagnostics.grid(row=0, column=0, sticky="ew")
                separator.configure(width=1, height=1)
                separator.grid(row=1, column=0, sticky="ew", pady=18)
                sync_cfg.grid(row=2, column=0, sticky="ew")
            else:
                sync_body.grid_columnconfigure(0, weight=1, uniform="sync")
                sync_body.grid_columnconfigure(1, weight=0, uniform="")
                sync_body.grid_columnconfigure(2, weight=1, uniform="sync")
                diagnostics.grid(row=0, column=0, sticky="nsew", padx=(0, 34))
                separator.configure(width=1, height=1)
                separator.grid(row=0, column=1, sticky="ns")
                sync_cfg.grid(row=0, column=2, sticky="nsew", padx=(34, 0))

        sync_body.bind("<Configure>", _layout_sync_columns)

        tk.Frame(inner, bg=BORDER_COLOR, height=1).pack(fill="x", pady=(0, 18))
        btn_row = tk.Frame(inner, bg=WHITE)
        btn_row.pack(fill="x")
        self._settings_sync_now_btn = RoundedButton(
            btn_row,
            text="Sync Now",
            command=self._on_manual_sync_now,
            radius=7,
            bg_color=PRIMARY_BLUE,
            fg_color=WHITE,
            font=(FONT_FAMILY, 10, "bold"),
            shadow_color="#D8E1EC",
            width=138,
            height=46,
        )
        self._settings_sync_now_btn.text = "Sync Now"
        self._settings_sync_now_btn.pack(side="left")

        self._sync_log_btn = RoundedButton(
            btn_row,
            text="View Logs",
            command=self._show_sync_logs,
            radius=7,
            bg_color=TAB_DARK,
            fg_color=WHITE,
            font=(FONT_FAMILY, 10, "bold"),
            shadow_color="#D8E1EC",
            width=138,
            height=46,
        )
        self._sync_log_btn.text = "View Logs"
        self._sync_log_btn.pack(side="left", padx=(12, 0))

        wifi_card = GroupCard(main, radius=8, bg_color=WHITE, padding=24)
        wifi_card.pack(fill="x", pady=(10, 22))
        wifi_inner = wifi_card.inner_frame

        self._wifi_status_var = tk.StringVar(value="Status: Unknown")
        self._wifi_hint_var = tk.StringVar(value="Scan for nearby Wi-Fi networks, then choose one to connect.")
        self._wifi_ssid_var = tk.StringVar()
        self._wifi_pwd_var = tk.StringVar()
        self._wifi_networks = []
        self._wifi_scan_busy = False
        self._wifi_connect_busy = False
        self._wifi_scan_silent = False
        self._wifi_auto_scan_interval_ms = 15000

        wifi_header = tk.Frame(wifi_inner, bg=WHITE)
        wifi_header.pack(fill="x", pady=(0, 18))
        _settings_icon(wifi_header, "wifi").pack(side="left", padx=(0, 18))
        wifi_heading = tk.Frame(wifi_header, bg=WHITE)
        wifi_heading.pack(side="left", fill="y")
        tk.Label(wifi_heading, text="Connectivity", font=(FONT_FAMILY, 16, "bold"), fg=DARK_TEXT, bg=WHITE).pack(anchor="w", pady=(2, 0))
        self._wifi_status_label = tk.Label(
            wifi_heading,
            textvariable=self._wifi_status_var,
            font=(FONT_FAMILY, 10),
            fg=MID_TEXT,
            bg=WHITE,
            anchor="w",
        )
        self._wifi_status_label.pack(anchor="w", pady=(8, 0))

        status_chip_row = tk.Frame(wifi_inner, bg=WHITE)
        status_chip_row.pack(fill="x", pady=(0, 16))
        self._wifi_hint_label = tk.Label(
            status_chip_row,
            textvariable=self._wifi_hint_var,
            font=(FONT_FAMILY, 10),
            fg=MID_TEXT,
            bg="#F8FAFD",
            padx=14,
            pady=10,
            anchor="w",
            justify="left",
        )
        self._wifi_hint_label.pack(fill="x")

        tk.Label(
            wifi_inner,
            text="Network",
            font=(FONT_FAMILY, 11, "bold"),
            fg=DARK_TEXT,
            bg=WHITE,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        scan_row = tk.Frame(wifi_inner, bg=WHITE)
        scan_row.pack(fill="x", pady=(0, 12))

        self._wifi_combo = ttk.Combobox(
            scan_row, textvariable=self._wifi_ssid_var, state="readonly",
            font=(FONT_FAMILY, 11), style="Figma.TCombobox"
        )
        self._wifi_combo.pack(side="left", fill="x", expand=True, ipady=7)
        self._wifi_combo.bind("<<ComboboxSelected>>", self._on_wifi_network_selected)

        self._wifi_scan_btn = RoundedButton(
            scan_row, text="Scan", command=self._scan_wifi_networks,
            radius=7, bg_color=PRIMARY_BLUE, fg_color=WHITE,
            font=(FONT_FAMILY, 10, "bold"), shadow_color="#D8E1EC", width=96, height=48
        )
        self._wifi_scan_btn.text = "Scan"
        self._wifi_scan_btn.pack(side="right", padx=(16, 0))

        tk.Label(
            wifi_inner,
            text="Choose a network from the scan results, then enter its password below.",
            font=(FONT_FAMILY, 10),
            fg=MID_TEXT,
            bg=WHITE,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(0, 8))

        conn_row = tk.Frame(wifi_inner, bg=WHITE)
        conn_row.pack(fill="x")

        self._wifi_pwd_entry = RoundedEntry(
            conn_row, placeholder="Password", height=48, radius=7, bg=INPUT_BG,
            font=(FONT_FAMILY, 11), textvariable=self._wifi_pwd_var
        )
        self._wifi_pwd_entry.entry.config(show="*")
        self._wifi_pwd_entry.pack(side="left", fill="x", expand=True)

        self._wifi_connect_btn = RoundedButton(
            conn_row, text="Connect", command=self._connect_to_wifi,
            radius=7, bg_color=SUCCESS_GREEN, fg_color=WHITE,
            font=(FONT_FAMILY, 10, "bold"), shadow_color="#D8E1EC", width=96, height=48
        )
        self._wifi_connect_btn.text = "Connect"
        self._wifi_connect_btn.pack(side="right", padx=(16, 0))

        power_card = GroupCard(main, radius=8, bg_color=WHITE, padding=24)
        power_card.pack(fill="x", pady=(0, 22))
        power_inner = power_card.inner_frame

        power_header = tk.Frame(power_inner, bg=WHITE)
        power_header.pack(fill="x", pady=(0, 12))
        tk.Label(power_header, text="Power", font=(FONT_FAMILY, 16, "bold"), fg=DARK_TEXT, bg=WHITE).pack(anchor="w")
        tk.Label(
            power_header,
            text="Use this before switching off external power to help prevent Raspberry Pi OS corruption.",
            font=(FONT_FAMILY, 10),
            fg=MID_TEXT,
            bg=WHITE,
            anchor="w",
            justify="left",
            wraplength=760,
        ).pack(anchor="w", pady=(8, 0))

        power_btn_row = tk.Frame(power_inner, bg=WHITE)
        power_btn_row.pack(fill="x")
        self._power_off_btn = RoundedButton(
            power_btn_row,
            text="Power Off Device",
            command=self._confirm_power_off,
            radius=7,
            bg_color="#B91C1C",
            fg_color=WHITE,
            font=(FONT_FAMILY, 10, "bold"),
            shadow_color="#D8E1EC",
            width=168,
            height=48,
        )
        self._power_off_btn.text = "Power Off Device"
        self._power_off_btn.pack(side="left")

        self.after(500, lambda: self._scan_wifi_networks(silent=True))
        self.after(self._wifi_auto_scan_interval_ms, self._poll_wifi_networks)
        self.after(2000, self._poll_wifi_status)

    def _redraw_zone_card(self, event=None):
        c = self._zone_info_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1: return

        zone_name = self._current_zone.get()
        zone_data = self._zones_data.get(zone_name, {"households": 0, "read": 0, "flagged": 0})
        total = zone_data["households"]
        read = zone_data["read"]
        pct = int((read / total) * 100) if total > 0 else 0

        self._draw_rr(c, 4, 6, w - 1, h, 8, fill="#DDE5EF", outline="")
        self._draw_rr(c, 1, 1, w - 4, h - 5, 8, fill=WHITE, outline=BORDER_COLOR, width=1)
        c.create_text(28, 38, text=zone_name, font=(FONT_FAMILY, 22, "bold"), fill=DARK_TEXT, anchor="w")
        c.create_text(28, 68, text=f"{total} households assigned", font=(FONT_FAMILY, 10), fill=MID_TEXT, anchor="w")
        c.create_text(28, 112, text=f"{pct}%", font=(FONT_FAMILY, 31, "bold"), fill=SUCCESS_TEXT, anchor="w")
        c.create_text(28, 138, text="Complete", font=(FONT_FAMILY, 10, "bold"), fill=MID_TEXT, anchor="w")
        
        # Interactive Sync Button
        sync_bg = self._draw_rr(c, w - 142, 24, w - 26, 68, 7, fill=WHITE, outline="#BFDBFE", width=1, tags="sync_btn")
        c.create_text(w - 84, 46, text="Sync Now", font=(FONT_FAMILY, 10, "bold"), fill=PRIMARY_BLUE, anchor="center", tags="sync_btn")
        
        c.tag_bind("sync_btn", "<Enter>", lambda e: c.itemconfig(sync_bg, fill="#DBEAFE"))
        c.tag_bind("sync_btn", "<Leave>", lambda e: c.itemconfig(sync_bg, fill=WHITE))
        c.tag_bind("sync_btn", "<Button-1>", lambda e: self._on_sync())

    def _redraw_progress_card(self, event=None, anim_fraction=None):
        c = self._progress_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1: return

        zone_name = self._current_zone.get()
        zone_data = self._zones_data.get(zone_name, {"households": 0, "read": 0, "flagged": 0})
        total = zone_data["households"]
        read = zone_data["read"]
        flagged = zone_data["flagged"]
        remaining = total - read
        target_frac = read / total if total > 0 else 0

        frac = anim_fraction if anim_fraction is not None else target_frac

        self._draw_rr(c, 4, 6, w - 1, h, 8, fill="#D9E2EF", outline="")
        self._draw_rr(c, 1, 1, w - 4, h - 5, 8, fill="#1F4FC4", outline="")
        c.create_rectangle(6, 18, w - 9, 100, fill="#2458CF", outline="")
        c.create_rectangle(6, 100, w - 9, 190, fill="#2253C8", outline="")
        c.create_rectangle(6, 190, w - 9, h - 14, fill="#1F4FC0", outline="")
        cx = w // 2

        c.create_text(cx, 34, text="Today's Progress", font=(FONT_FAMILY, 10, "bold"), fill=WHITE)
        c.create_text(cx, 94, text=f"{read}/{total}", font=(FONT_FAMILY, 52, "bold"), fill=WHITE)
        c.create_text(cx, 137, text="Meters Read", font=(FONT_FAMILY, 11), fill="#D5E5FF")

        bar_x1, bar_x2 = 30, w - 30
        bar_width = bar_x2 - bar_x1
        bar_y, bar_h = 165, 14

        self._draw_rr(c, bar_x1, bar_y, bar_x2, bar_y + bar_h, 7, fill="#4A70CD", outline="")
        filled_w = int(bar_width * frac)
        if filled_w > 18:
            self._draw_rr(c, bar_x1, bar_y, bar_x1 + filled_w, bar_y + bar_h, 7, fill="#4ADE80", outline="")

        div_y = 204
        c.create_line(30, div_y, w - 30, div_y, fill="#4D74D0", width=1)
        c.create_line(cx, div_y + 22, cx, h - 62, fill="#6E8EDD", width=1)

        c.create_text(w // 4, 255, text=str(remaining), font=(FONT_FAMILY, 31, "bold"), fill=WHITE)
        c.create_text(w // 4, 287, text="Remaining", font=(FONT_FAMILY, 10), fill="#D5E5FF")
        c.create_text(3 * w // 4, 255, text=str(flagged), font=(FONT_FAMILY, 31, "bold"), fill="#FACC15")
        c.create_text(3 * w // 4, 287, text="Flagged", font=(FONT_FAMILY, 10), fill="#D5E5FF")
        
        # Click hint
        c.create_text(cx, h - 16, text="Tap for details", font=(FONT_FAMILY, 9), fill="#93C5FD")
        
        # Make clickable
        c.bind("<Button-1>", lambda e: self._show_progress_details())
        for item in c.find_all():
            c.tag_bind(item, "<Button-1>", lambda e: self._show_progress_details())
            c.tag_bind(item, "<Enter>", lambda e: c.config(cursor="hand2"))
            c.tag_bind(item, "<Leave>", lambda e: c.config(cursor=""))

    def _animate_progress_bar(self):
        if self._progress_anim_id:
            self.after_cancel(self._progress_anim_id)

        zone_name = self._current_zone.get()
        zone_data = self._zones_data.get(zone_name, {"households": 0, "read": 0, "flagged": 0})
        total = zone_data["households"]
        read = zone_data["read"]
        target = read / total if total > 0 else 0

        self._progress_anim_fraction = 0.0
        duration_ms = 800
        steps = 30
        step_ms = duration_ms // steps
        increment = target / steps if steps > 0 else 0

        def _step():
            self._progress_anim_fraction += increment
            if self._progress_anim_fraction >= target:
                self._progress_anim_fraction = target
                self._redraw_progress_card(anim_fraction=target)
                return
            self._redraw_progress_card(anim_fraction=self._progress_anim_fraction)
            self._progress_anim_id = self.after(step_ms, _step)
        _step()

    def _on_zone_change(self, event=None):
        if hasattr(self, '_active_zone_label') and self._active_zone_label.winfo_exists():
            self._active_zone_label.config(text=self._current_zone.get())
        # Clear search and consumer on zone change
        self._hide_autocomplete()
        if hasattr(self, 'search_var'):
            self.search_var.set("")
        self._current_consumer = None
        self._clear_consumer_details()
        self._refresh_zone_stats()

    def _show_progress_details(self):
        """Show detailed table of all consumers within current window."""
        # Prevent duplicate frames
        if hasattr(self, '_progress_details_frame') and self._progress_details_frame.winfo_exists():
            return
        
        zone_name = self._current_zone.get()
        consumers = get_zone_consumers_with_status(zone_name)
        
        if not consumers:
            messagebox.showinfo("No Data", f"No consumers found in {zone_name}")
            return
        
        # Hide progress content and show details
        self._progress_content.pack_forget()
        
        # Create details view frame
        details_frame = tk.Frame(self.progress_frame, bg=BG_COLOR)
        details_frame.pack(fill="both", expand=True)
        self._progress_details_frame = details_frame  # Store reference
        
        # Header with back button
        header = tk.Frame(details_frame, bg=HEADER_BLUE, height=50)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        # Back button (left)
        back_btn = tk.Label(header, text="←", font=(FONT_FAMILY, 16, "bold"),
                          bg=HEADER_BLUE, fg=WHITE, cursor="hand2", padx=15)
        back_btn.pack(side="left", fill="y")
        back_btn.bind("<Button-1>", lambda e: self._hide_progress_details())
        
        # Title (center)
        tk.Label(header, text=f"{zone_name} - Details", 
                font=(FONT_FAMILY, 14, "bold"), bg=HEADER_BLUE, fg=WHITE).pack(side="left", expand=True, padx=(0, 60))
        
        # Stats summary bar
        read_count = sum(1 for c in consumers if c['is_read'])
        total = len(consumers)
        summary = tk.Frame(details_frame, bg=WHITE, padx=15, pady=10)
        summary.pack(fill="x", padx=15, pady=10)
        tk.Label(summary, text=f"Total: {total} | Read: {read_count} | Remaining: {total - read_count}",
                font=(FONT_FAMILY, 11, "bold"), bg=WHITE, fg=DARK_TEXT).pack(side="left")
        
        # Create table using a simpler approach for devices
        table_frame = tk.Frame(details_frame, bg=BORDER_COLOR)
        table_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        # Column headers
        headers_frame = tk.Frame(table_frame, bg=BORDER_COLOR)
        headers_frame.pack(fill="x", pady=(1, 1))
        
        headers = [
            ("Meter", 10, "w"),
            ("Name", 16, "w"),
            ("Status", 6, "center"),
            ("Reading", 8, "center"),
            ("Action", 10, "center")
        ]
        for text, width, anchor in headers:
            lbl = tk.Label(headers_frame, text=text, font=(FONT_FAMILY, 9, "bold"),
                         bg=BG_COLOR, fg=MID_TEXT, width=width, anchor=anchor)
            lbl.pack(side="left", padx=1, pady=4)
        
        # Scrollable content
        canvas_frame = tk.Frame(table_frame, bg=BORDER_COLOR)
        canvas_frame.pack(fill="both", expand=True, pady=(0, 1))
        
        canvas = tk.Canvas(canvas_frame, bg=BORDER_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        rows_frame = tk.Frame(canvas, bg=BORDER_COLOR)
        canvas_window = canvas.create_window((0, 0), window=rows_frame, anchor="nw")
        
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
            rows_frame.config(width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)
        
        # Store reading data for reprint
        self._progress_reading_data = {}
        
        # Populate rows
        for i, consumer in enumerate(consumers):
            is_read = consumer['is_read']
            bg_color = "#E8F5E9" if is_read else WHITE
            
            row_frame = tk.Frame(rows_frame, bg=bg_color, height=36)
            row_frame.pack(fill="x", pady=(0, 1))
            row_frame.pack_propagate(False)
            
            # Meter No
            tk.Label(row_frame, text=consumer['meter_no'], font=(FONT_FAMILY, 10),
                    bg=bg_color, fg=DARK_TEXT, width=10, anchor="w").pack(side="left", padx=3, pady=6)
            
            # Name (reduced to width 15)
            name = consumer['name'][:13] + "..." if len(consumer['name']) > 13 else consumer['name']
            tk.Label(row_frame, text=name, font=(FONT_FAMILY, 10),
                    bg=bg_color, fg=DARK_TEXT, width=15, anchor="w").pack(side="left", padx=3, pady=6)
            
            # Status (width 6, centered)
            status_text = "Read" if is_read else "Pending"
            status_color = SUCCESS_GREEN if is_read else MID_TEXT
            status_lbl = tk.Label(row_frame, text=status_text, font=(FONT_FAMILY, 8, "bold"),
                    bg=bg_color, fg=status_color, width=6, anchor="center")
            status_lbl.pack(side="left", padx=3, pady=6)
            # Tooltip effect on hover
            status_lbl.bind("<Enter>", lambda e, lbl=status_lbl, txt=status_text: lbl.config(text="Read" if txt == "Read" else "Pending"))
            status_lbl.bind("<Leave>", lambda e, lbl=status_lbl, txt=status_text: lbl.config(text=txt))
            
            # Reading (width 8, centered to align with header)
            reading_val = str(consumer['reading_value']) if is_read and consumer['reading_value'] else "-"
            tk.Label(row_frame, text=reading_val, font=(FONT_FAMILY, 10),
                    bg=bg_color, fg=DARK_TEXT, width=8, anchor="center").pack(side="left", padx=3, pady=6)
            
            # Reprint button for read items (width 10, centered)
            if is_read:
                reprint_btn = tk.Label(row_frame, text="Print", font=(FONT_FAMILY, 10, "bold"),
                                     bg=bg_color, fg=PRIMARY_BLUE, cursor="hand2", width=10, anchor="center")
                reprint_btn.pack(side="left", padx=3, pady=4)
                
                # Store data for reprint
                self._progress_reading_data[id(reprint_btn)] = {
                    'consumer': consumer,
                    'previous': consumer['previous_reading'],
                    'present': consumer['reading_value'],
                    'exception': consumer['exception'] or "None"
                }
                
                # Bind click to reprint
                reprint_btn.bind("<Button-1>", 
                    lambda e, btn_id=id(reprint_btn): self._reprint_from_details(btn_id))
            else:
                tk.Label(row_frame, text="", font=(FONT_FAMILY, 10),
                        bg=bg_color, width=10).pack(side="left", padx=3, pady=4)
        
        # Update canvas scroll region
        rows_frame.update_idletasks()
        canvas.config(scrollregion=canvas.bbox("all"))
    
    def _hide_progress_details(self):
        """Hide details view and return to progress view."""
        if hasattr(self, '_progress_details_frame'):
            self._progress_details_frame.destroy()
            del self._progress_details_frame
        self._progress_content.pack(fill="both", expand=True)
    
    def _reprint_from_details(self, btn_id):
        """Handle reprint request from progress details."""
        if not hasattr(self, '_progress_reading_data') or btn_id not in self._progress_reading_data:
            return
        
        data = self._progress_reading_data[btn_id]
        consumer = data['consumer']
        
        if messagebox.askyesno("Reprint Receipt", 
                              f"Reprint receipt for {consumer['name']}?\n\n"
                              f"Meter: {consumer['meter_no']}\n"
                              f"Reading: {data['present']}"):
            latest_entry = get_latest_receipt_print(consumer["id"])
            receipt_text = latest_entry["receipt_text"] if latest_entry else None
            self._deliver_receipt(
                consumer,
                data["previous"],
                data["present"],
                data["exception"],
                self._current_user["name"] if self._current_user else "Field Reader",
                latest_entry.get("reading_id") if latest_entry else data.get("reading_id"),
                "reprint",
                receipt_text,
            )
    
    def _on_sync(self):
        self._spawn_overlay("Syncing...", "Refreshing from main database", self._do_sync)

    def _do_sync(self):
        if self._sync_dal:
            try:
                result = self._sync_dal.syncPendingReadings()
                self._sync_state = "Online" if self._sync_dal.is_online() else "Offline"
                self._sync_sync_result = result
            except Exception as exc:
                self._sync_state = "Sync Failed"
                self._sync_sync_result = {"status": "failed", "error": str(exc)}
        time.sleep(0.8)
        self.after(0, self._finish_sync)

    def _finish_sync(self):
        self._dismiss_overlay()
        mirrored_count = self._hydrate_local_consumers_from_sync()
        self._refresh_zone_stats()
        self._refresh_sync_status_ui()
        if hasattr(self, "_sync_sync_result") and self._sync_sync_result:
            r = self._sync_sync_result
            if r.get("status") == "done":
                messagebox.showinfo(
                    "Sync Complete",
                    f"Synced: {r.get('synced', 0)}\nFailed: {r.get('failed', 0)}\nConflicts: {r.get('conflicts', 0)}\nPulled: {getattr(self, '_last_pull_count', 0)}\nMirrored: {mirrored_count}",
                )
            elif r.get("status") == "offline":
                messagebox.showwarning("Sync Offline", "Device is offline. Pending readings remain queued.")
            else:
                messagebox.showerror("Sync Failed", str(r.get("error", "Unknown sync error")))
        else:
            messagebox.showinfo("Sync Complete", "Zone data refreshed from the database.")

    def _on_manual_sync_now(self):
        self._refresh_sync_status_ui("checking connection")
        self._on_sync()

    def _on_sync_config_changed(self):
        try:
            interval = int(self._auto_pull_interval_sec.get() or 60)
        except Exception:
            interval = 60
        interval = max(15, interval)
        self._auto_pull_interval_sec.set(interval)
        self._schedule_auto_pull()
        mode_text = f"pull={'on' if self._auto_pull_enabled.get() else 'off'}, push={'on' if self._auto_push_enabled.get() else 'off'}, {interval}s"
        self._refresh_sync_status_ui(mode_text)

    def _confirm_power_off(self):
        pending = int(getattr(self, "_sync_pending_count", 0) or 0)
        warning = (
            "Power off the device safely?\n\n"
            "The app will sync pending readings first, then send a proper shutdown command to the Raspberry Pi to help prevent Raspberry Pi OS corruption.\n"
            "Only remove external power after the screen and Pi have fully shut down."
        )
        if pending > 0:
            warning += f"\n\nWarning: {pending} reading(s) are still pending sync."

        if not messagebox.askyesno("Power Off Device", warning):
            return

        if os.name == "nt":
            messagebox.showinfo(
                "Windows Preview",
                "Safe power-off is intended for the Raspberry Pi device.\n\n"
                "On the Pi, this button will request a graceful OS shutdown before external power is removed.",
            )
            return

        self._spawn_overlay(
            "Preparing Shutdown...",
            "Syncing pending readings before power off",
            self._sync_then_power_off_task,
        )

    def _sync_then_power_off_task(self):
        try:
            if self._sync_dal:
                result = self._sync_dal.syncPendingReadings()
                self._sync_state = "Online" if self._sync_dal.is_online() else "Offline"
                self._sync_sync_result = result

                if result.get("status") != "done":
                    detail = str(result.get("error") or result.get("status") or "Sync failed before shutdown.")
                    self.after(0, lambda msg=detail: self._on_power_off_blocked(msg))
                    return

                pending_after_sync = len(self._sync_dal.listPendingSyncReadings())
                self._sync_pending_count = pending_after_sync
                if pending_after_sync > 0:
                    self.after(
                        0,
                        lambda count=pending_after_sync: self._on_power_off_blocked(
                            f"{count} reading(s) are still pending after sync. Shutdown was cancelled."
                        ),
                    )
                    return

                self._hydrate_local_consumers_from_sync()
                self.after(0, self._refresh_zone_stats)
                self.after(0, self._refresh_sync_status_ui)
            self._power_off_device_task()
        except Exception as exc:
            self._sync_state = "Sync Failed"
            self.after(0, lambda msg=str(exc): self._on_power_off_blocked(msg or "Sync failed before shutdown."))

    def _power_off_device_task(self):
        commands = [
            ["systemctl", "poweroff"],
            ["shutdown", "-h", "now"],
            ["poweroff"],
            ["sudo", "-n", "shutdown", "-h", "now"],
            ["sudo", "-n", "poweroff"],
        ]

        last_error = "Power-off command failed."
        for command in commands:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=12,
                    check=False,
                )
                if result.returncode == 0:
                    return
                detail = (result.stderr or result.stdout or "").strip()
                if detail:
                    last_error = detail
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                return
            except Exception as exc:
                last_error = str(exc) or last_error

        self.after(0, lambda msg=last_error: self._on_power_off_failed(msg))

    def _on_power_off_failed(self, detail: str):
        self._dismiss_overlay()
        messagebox.showerror(
            "Power Off Failed",
            f"Unable to request a safe Raspberry Pi shutdown.\n\n{detail}",
        )

    def _on_power_off_blocked(self, detail: str):
        self._dismiss_overlay()
        self._refresh_sync_status_ui()
        messagebox.showwarning(
            "Shutdown Cancelled",
            f"Device shutdown was stopped because the pre-shutdown sync did not complete cleanly.\n\n{detail}",
        )

    # --- Native Wi-Fi Settings Handlers --------------------------------------
    def _set_wifi_status(self, text: str, color: str = MID_TEXT):
        self._wifi_status_var.set(text)
        if hasattr(self, "_wifi_status_label") and self._wifi_status_label.winfo_exists():
            self._wifi_status_label.config(fg=color)

    def _refresh_wifi_network_list(self):
        if self._wifi_networks:
            self._wifi_hint_var.set(
                f"{len(self._wifi_networks)} network(s) available nearby."
            )
        else:
            self._wifi_hint_var.set("No nearby Wi-Fi networks found. Tap Scan to refresh.")

    def _on_wifi_network_selected(self, event=None):
        selected = self._wifi_ssid_var.get().strip()
        if selected:
            self._wifi_hint_var.set(f"Selected network: {selected}")

    def _scan_wifi_networks(self, silent: bool = False):
        if self._wifi_scan_busy:
            return
        self._wifi_scan_busy = True
        self._wifi_scan_silent = silent
        if not silent:
            self._set_wifi_status("Status: Scanning...", PRIMARY_BLUE)
        self._wifi_hint_var.set("Scanning for nearby Wi-Fi networks...")
        self._wifi_scan_btn.text = "Scanning..."
        threading.Thread(target=self._scan_wifi_networks_thread, daemon=True).start()

    def _scan_wifi_networks_thread(self):
        try:
            command = (
                ["netsh", "wlan", "show", "networks", "mode=bssid"]
                if os.name == "nt"
                else ["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"]
            )
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "Wi-Fi scan failed").strip()
                if os.name == "nt" and ("location permission" in detail.lower() or "requires elevation" in detail.lower()):
                    detail = "Windows requires Location services for Wi-Fi scanning. Enable Location in Privacy & security, then scan again."
                raise RuntimeError(detail)
            if os.name == "nt":
                networks = sorted({
                    match.group(1).strip()
                    for line in result.stdout.splitlines()
                    if (match := re.match(r"^\s*SSID\s+\d+\s*:\s*(.+)$", line))
                    and match.group(1).strip()
                })
            else:
                networks = sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})
            self.after(0, lambda: self._on_scan_complete(networks, None))
        except FileNotFoundError:
            tool = "netsh" if os.name == "nt" else "nmcli"
            self.after(0, lambda name=tool: self._on_scan_complete([], f"Wi-Fi utility '{name}' is not installed."))
        except subprocess.TimeoutExpired:
            self.after(0, lambda: self._on_scan_complete([], "Wi-Fi scan timed out."))
        except Exception as exc:
            error_text = str(exc) or "Wi-Fi scan failed."
            self.after(0, lambda msg=error_text: self._on_scan_complete([], msg))

    def _on_scan_complete(self, networks, error):
        self._wifi_scan_busy = False
        self._wifi_scan_btn.text = "Scan"
        silent = self._wifi_scan_silent
        self._wifi_scan_silent = False
        if error:
            self._wifi_networks = []
            self._wifi_combo["values"] = []
            self._refresh_wifi_network_list()
            if not silent:
                self._set_wifi_status(f"Status: Error - {error}", INVALID_TEXT)
            if not silent:
                messagebox.showerror("Wi-Fi Scan Failed", error)
            return

        self._wifi_networks = networks
        self._wifi_combo["values"] = self._wifi_networks
        self._refresh_wifi_network_list()
        if self._wifi_networks and not self._wifi_ssid_var.get():
            self._wifi_ssid_var.set(self._wifi_networks[0])
        if silent:
            return
        if self._wifi_networks:
            self._set_wifi_status(f"Status: Scan Complete ({len(self._wifi_networks)} found)", SUCCESS_TEXT)
        else:
            self._set_wifi_status("Status: No networks found", WARNING_TEXT)

    def _poll_wifi_networks(self):
        if not self._wifi_scan_busy and not self._wifi_connect_busy:
            self._scan_wifi_networks(silent=True)
        self.after(self._wifi_auto_scan_interval_ms, self._poll_wifi_networks)

    def _connect_to_wifi(self):
        if self._wifi_connect_busy:
            return
        ssid = self._wifi_ssid_var.get().strip()
        pwd = self._wifi_pwd_entry.get()
        if not ssid:
            self._set_wifi_status("Status: Error - Enter or select an SSID", INVALID_TEXT)
            messagebox.showwarning("Wi-Fi", "Enter or select a Wi-Fi network first.")
            return
        if os.name == "nt":
            self._set_wifi_status("Status: Raspberry Pi Wi-Fi (Windows preview)", WARNING_TEXT)
            messagebox.showinfo(
                "Raspberry Pi Wi-Fi",
                "Wi-Fi connection is available on the Raspberry Pi. Windows mode supports network scanning and status checks for UI testing.",
            )
            return

        self._wifi_connect_busy = True
        self._set_wifi_status(f"Status: Connecting to {ssid}...", PRIMARY_BLUE)
        self._wifi_connect_btn.text = "Connecting..."
        threading.Thread(target=self._connect_to_wifi_thread, args=(ssid, pwd), daemon=True).start()

    def _connect_to_wifi_thread(self, ssid, pwd):
        try:
            cmd = ["nmcli", "dev", "wifi", "connect", ssid]
            if pwd:
                cmd.extend(["password", pwd])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=35, check=False)
            if result.returncode == 0:
                self.after(0, lambda: self._finish_wifi_connection(True, ssid, ""))
            else:
                detail = (result.stderr or result.stdout or "Connection failed. Check the password.").strip()
                self.after(0, lambda msg=detail: self._finish_wifi_connection(False, ssid, msg))
        except FileNotFoundError:
            self.after(0, lambda: self._finish_wifi_connection(False, ssid, "NetworkManager command 'nmcli' was not found."))
        except subprocess.TimeoutExpired:
            self.after(0, lambda: self._finish_wifi_connection(False, ssid, "Connection attempt timed out."))
        except Exception as exc:
            error_text = str(exc) or "Connection failed."
            self.after(0, lambda msg=error_text: self._finish_wifi_connection(False, ssid, msg))

    def _finish_wifi_connection(self, success, ssid, detail):
        self._wifi_connect_busy = False
        self._wifi_connect_btn.text = "Connect"
        if success:
            self._wifi_pwd_var.set("")
            self._set_wifi_status(f"Status: Connected to {ssid}", SUCCESS_TEXT)
            messagebox.showinfo("Wi-Fi Connected", f"Connected to {ssid} successfully.")
        else:
            self._set_wifi_status(f"Status: Error - {detail}", INVALID_TEXT)
            messagebox.showerror("Wi-Fi Connection Failed", detail)

    def _poll_wifi_status(self):
        if not self._wifi_scan_busy and not self._wifi_connect_busy:
            threading.Thread(target=self._poll_wifi_status_thread, daemon=True).start()
        self.after(5000, self._poll_wifi_status)

    def _poll_wifi_status_thread(self):
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["netsh", "wlan", "show", "interfaces"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "Unable to check Wi-Fi status").strip()
                    if "requires elevation" in detail.lower() or "access WLAN information" in detail:
                        self.after(0, lambda: self._set_wifi_status("Status: Raspberry Pi Wi-Fi (Windows preview)", WARNING_TEXT))
                        return
                    raise RuntimeError(detail)
                connected = re.search(r"^\s*State\s*:\s*connected\s*$", result.stdout, re.MULTILINE | re.IGNORECASE)
                ssid_match = re.search(r"^\s*SSID\s*:\s*(.+)$", result.stdout, re.MULTILINE | re.IGNORECASE)
                if connected and ssid_match:
                    ssid = ssid_match.group(1).strip()
                    self.after(0, lambda name=ssid: self._set_wifi_status(f"Status: Connected to {name}", SUCCESS_TEXT))
                elif "There is no wireless interface" in result.stdout:
                    self.after(0, lambda: self._set_wifi_status("Status: No Wi-Fi adapter detected", WARNING_TEXT))
                else:
                    self.after(0, lambda: self._set_wifi_status("Status: Disconnected", MID_TEXT))
                return
            result = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "Unable to check Wi-Fi status").strip()
                self.after(0, lambda msg=detail: self._set_wifi_status(f"Status: Error - {msg}", INVALID_TEXT))
                return

            wifi_found = False
            for line in result.stdout.splitlines():
                parts = line.split(":", 3)
                if len(parts) < 4 or parts[1].strip() != "wifi":
                    continue
                wifi_found = True
                state = parts[2].strip()
                connection = parts[3].strip()
                if state == "connected":
                    self.after(0, lambda name=connection: self._set_wifi_status(f"Status: Connected to {name}", SUCCESS_TEXT))
                    return

            if wifi_found:
                self.after(0, lambda: self._set_wifi_status("Status: Disconnected", MID_TEXT))
            else:
                self.after(0, lambda: self._set_wifi_status("Status: Error - No Wi-Fi adapter detected", WARNING_TEXT))
        except FileNotFoundError:
            tool = "netsh" if os.name == "nt" else "nmcli"
            self.after(0, lambda name=tool: self._set_wifi_status(f"Status: Wi-Fi utility '{name}' is not installed", WARNING_TEXT))
        except subprocess.TimeoutExpired:
            self.after(0, lambda: self._set_wifi_status("Status: Wi-Fi status check timed out", WARNING_TEXT))
        except Exception as exc:
            error_text = str(exc) or "Unable to check Wi-Fi status"
            self.after(0, lambda msg=error_text: self._set_wifi_status(f"Status: Error - {msg}", INVALID_TEXT))

    def _show_sync_logs(self):
        if not self._sync_dal:
            messagebox.showinfo("Sync Logs", "Sync layer is not enabled/configured.")
            return
        try:
            entries = self._sync_dal.get_recent_audit_entries(limit=25)
        except Exception as exc:
            messagebox.showerror("Sync Logs", f"Unable to load logs: {exc}")
            return

        popup = tk.Toplevel(self)
        popup.title("Sync Logs")
        popup.geometry("460x420")
        popup.configure(bg=BG_COLOR)

        title = tk.Label(popup, text="Recent Sync Activity", font=(FONT_FAMILY, 12, "bold"), bg=BG_COLOR, fg=DARK_TEXT)
        title.pack(anchor="w", padx=12, pady=(10, 6))

        text = tk.Text(popup, wrap="word", font=(FONT_FAMILY, 9), bg=WHITE, fg=DARK_TEXT, relief="flat", bd=1)
        text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        if not entries:
            text.insert("end", "No sync log entries yet.")
        else:
            for row in entries:
                created = row.get("created_at", "")
                status = str(row.get("status", "")).upper()
                msg = row.get("message", "")
                qid = row.get("queue_id")
                text.insert("end", f"[{created}] {status}  queue_id={qid}\n{msg}\n\n")
        text.configure(state="disabled")

    def _refresh_zone_stats(self):
        """Reload zone statistics from the database and redraw the progress tab."""
        self._zones_data = get_zone_stats()
        self._ensure_current_zone()
        if hasattr(self, "_zone_combo") and self._zone_combo.winfo_exists():
            self._zone_combo.configure(values=get_all_zone_names())
            if self._current_zone.get():
                self._zone_combo.set(self._current_zone.get())
        self._redraw_zone_card()
        self._animate_progress_bar()

    # -- Search & Load Consumer -------------------------------------------
    def _on_search_key(self, event=None):
        """Called on every keystroke to show live autocomplete suggestions."""
        # Ignore modifier keys
        if event and event.keysym in ('Return', 'Escape', 'Tab', 'Shift_L', 'Shift_R',
                                       'Control_L', 'Control_R', 'Alt_L', 'Alt_R'):
            if event.keysym == 'Escape':
                self._hide_autocomplete()
            return

        query = self.search_input.get().strip()
        if not query:
            self._hide_autocomplete()
            return

        zone = self._current_zone.get()
        unread_only = bool(self._search_unread_only.get())
        results = search_consumers_by_zone(query, zone, unread_only=unread_only)
        if not results:
            self._hide_autocomplete()
            return

        self._autocomplete_results = results
        self._show_autocomplete(results)

    def _show_autocomplete(self, results):
        """Display or update the autocomplete dropdown below the search input."""
        self._hide_autocomplete()

        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=BORDER_COLOR)
        self._autocomplete_popup = popup

        # Position directly below the search input
        x = self.search_input.winfo_rootx()
        y = self.search_input.winfo_rooty() + self.search_input.winfo_height()
        w = self.search_input.winfo_width()

        listbox = tk.Listbox(
            popup, font=(FONT_FAMILY, 11), bg=WHITE, fg=DARK_TEXT,
            selectbackground=PRIMARY_BLUE, selectforeground=WHITE,
            relief="flat", bd=0, highlightthickness=0,
            activestyle="none", cursor="hand2")

        for r in results:
            listbox.insert("end", f"  {r['meter_no']}  —  {r['name']}")

        row_height = 28
        total_h = min(len(results), 6) * row_height + 4
        popup.geometry(f"{w}x{total_h}+{x}+{y}")

        listbox.pack(fill="both", expand=True, padx=1, pady=1)
        listbox.bind("<ButtonRelease-1>", self._on_autocomplete_select)
        # Allow hovering to highlight
        listbox.bind("<Motion>", lambda e: listbox.activate(listbox.nearest(e.y)))
        self._autocomplete_listbox = listbox

    def _on_autocomplete_select(self, event=None):
        """Handle clicking on an autocomplete suggestion."""
        if not self._autocomplete_popup:
            return
        lb = self._autocomplete_listbox
        sel = lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._autocomplete_results):
            consumer = self._autocomplete_results[idx]
            self._load_consumer(consumer)
        self._hide_autocomplete()

    def _schedule_hide_autocomplete(self, event=None):
        """Delay hiding so click events on the popup can fire first."""
        self.after(200, self._hide_autocomplete)

    def _hide_autocomplete(self):
        """Destroy the autocomplete popup if it exists."""
        if self._autocomplete_popup and self._autocomplete_popup.winfo_exists():
            self._autocomplete_popup.destroy()
        self._autocomplete_popup = None

    def _on_search(self, event=None):
        self._hide_autocomplete()
        meter_no = self.search_var.get().strip()
        if not meter_no:
            messagebox.showinfo("Search", "Please enter a meter number.")
            return
        
        # If numeric, auto-prepend "MTR-"
        if meter_no.isdigit():
            padded_no = meter_no.zfill(3)
            meter_no = f"MTR-{padded_no}"
        
        unread_only = bool(self._search_unread_only.get())
        consumer = search_consumer(meter_no, unread_only=unread_only)
        if consumer is None:
            # Also try zone-filtered partial search
            zone = self._current_zone.get()
            results = search_consumers_by_zone(meter_no, zone, unread_only=unread_only)
            if results:
                consumer = results[0]
            else:
                messagebox.showwarning("Not Found", f"No consumer found for '{meter_no}' in {zone}.")
                self._current_consumer = None
                self._clear_consumer_details()
                return
        self._load_consumer(consumer)

    def _on_search_mode_changed(self):
        """Refresh autocomplete/results when toggling unread filter."""
        self._hide_autocomplete()
        query = self.search_input.get().strip() if hasattr(self, "search_input") else ""
        if query:
            self._on_search_key()

    def _load_consumer(self, consumer):
        """Populate the UI with the given consumer data."""
        self._current_consumer = consumer
        self._detail_labels["Account No."].config(text=consumer["acct_no"])
        self._detail_labels["Name"].config(text=consumer["name"])
        self._detail_labels["Previous"].config(text=str(consumer["previous_reading"]))
        # Update search bar to show the meter number
        self.search_var.set(consumer["meter_no"])
        # Reset reading input
        self.present_var.set("")
        self._set_consumption_state("default", "", "-", "-")

    def _clear_consumer_details(self):
        for lbl in self._detail_labels.values():
            lbl.config(text="-")
        self.present_var.set("")
        self._set_consumption_state("default", "", "-", "-")

    # ----------------------------------------------------------------------
    #  VALIDATION & OVERLAYS
    # ----------------------------------------------------------------------
    @staticmethod
    def _validate_numeric(new_value):
        if new_value == "": return True
        return new_value.isdigit()

    def _update_consumption(self, *_):
        reading_str = self.present_var.get()
        if not reading_str or reading_str == "Enter current reading...":
            self._set_consumption_state("default", "", "-", "-")
            return
        if self._current_consumer is None:
            self._set_consumption_state("invalid", "No Consumer", "Search a meter first", "No consumer loaded")
            return
        try:
            present = int(reading_str)
        except ValueError:
            self._set_consumption_state("invalid", "Invalid Input", "Must be a number", "Invalid entry")
            return
        previous = self._current_consumer["previous_reading"]
        consumption = present - previous
        if consumption < 0:
            self._set_consumption_state("invalid", "INVALID READING", "Reading cannot be less than previous", f"Reading must be >= previous ({previous})")
            self._shake_widget(self.reading_input)
        elif consumption > HIGH_CONSUMPTION_THRESHOLD:
            self._set_consumption_state("warning", str(consumption), "Unusually high - please verify", "High consumption detected")
        else:
            self._set_consumption_state("valid", str(consumption), "Valid reading", "")

    def _set_consumption_state(self, state, title, message, validation_msg):
        # Store the state for print validation
        self._consumption_state = state
        
        if state == "valid":
            title_color = VALID_TEXT
            msg_color = VALID_TEXT
            self.reading_input.set_border_color(VALID_BORDER)
            self._validation_icon_label.config(text=validation_msg if validation_msg else "", fg=VALID_TEXT)
        elif state == "warning":
            title_color = WARNING_TEXT
            msg_color = WARNING_TEXT
            self.reading_input.set_border_color(WARNING_BORDER)
            self._validation_icon_label.config(text=validation_msg, fg=WARNING_TEXT)
        elif state == "invalid":
            title_color = INVALID_TEXT
            msg_color = INVALID_TEXT
            self.reading_input.set_border_color(INVALID_BORDER)
            self._validation_icon_label.config(text=validation_msg, fg=INVALID_TEXT)
        else:
            title_color = LIGHT_TEXT
            msg_color = LIGHT_TEXT
            self.reading_input.clear_border_override()
            self._validation_icon_label.config(text="", fg=BG_COLOR)

        self._cons_title_label.config(text=title, fg=title_color)
        self._cons_message_label.config(text=message, fg=msg_color)

    def _shake_widget(self, widget):
        for aid in self._shake_after_ids:
            self.after_cancel(aid)
        self._shake_after_ids.clear()
        original_x = widget.winfo_x()
        offsets = [8, -8, 6, -6, 4, -4, 2, -2, 0]
        delay = 0
        for offset in offsets:
            aid = self.after(delay, lambda o=offset: widget.place_configure(x=original_x + o) if widget.winfo_manager() == 'place' else None)
            self._shake_after_ids.append(aid)
            delay += 40

    def _on_print(self):
        if self._current_consumer is None:
            messagebox.showwarning("No Consumer", "Please search for a consumer first.")
            return
        reading = self.present_var.get()
        if not reading or reading == "Enter current reading...":
            messagebox.showwarning("Missing Reading", "Please enter a meter reading before printing.")
            return
        try:
            val = int(reading)
            previous = self._current_consumer["previous_reading"]
            if val < previous:
                messagebox.showerror("Invalid Reading", "Cannot print an invalid reading.")
                return
        except ValueError:
            messagebox.showerror("Invalid Input", "Reading must be a number.")
            return

        # Check paper status before printing
        paper_status = self.status_bar.get_paper_status()
        if not self.status_bar.can_print():
            self._show_paper_error(paper_status)
            return

        # Warn if paper is low
        if paper_status == "low":
            if not messagebox.askyesno("Paper Low", "Paper is running low.\n\nDo you want to continue printing?"):
                return
        
        # Check for high consumption warning - require confirmation
        if hasattr(self, '_consumption_state') and self._consumption_state == "warning":
            present = int(reading)
            previous = self._current_consumer["previous_reading"]
            consumption = present - previous
            if not messagebox.askyesno("High Consumption Warning", 
                                       f"Consumption ({consumption}) exceeds threshold ({HIGH_CONSUMPTION_THRESHOLD}).\n\n"
                                       f"This is an unusually high reading.\n\n"
                                       f"Do you want to proceed with printing?"):
                return
        
        # Show print confirmation
        consumer_name = self._current_consumer.get('name', 'Unknown')
        meter_no = self._current_consumer.get('meter_no', 'Unknown')
        if not messagebox.askyesno("Confirm Print", 
                                   f"Print receipt for:\n\n"
                                   f"Consumer: {consumer_name}\n"
                                   f"Meter: {meter_no}\n\n"
                                   f"Continue with printing?"):
            return

        self._show_saving_overlay()

    def _show_paper_error(self, status: str):
        """Show paper error dialog with reprint options."""
        if status == "out":
            messagebox.showerror("No Paper", "Cannot print: Paper is out.\n\nPlease load paper and try again.")
        elif status == "jam":
            result = messagebox.askyesno("Paper Jam",
                "Cannot print: Paper is jammed.\n\nPlease clear the jam and click Yes to retry, or No to save for reprint later.")
            if result:
                # User wants to retry - check paper status again
                if self.status_bar.can_print():
                    self._show_saving_overlay()
                else:
                    self._show_paper_error(self.status_bar.get_paper_status())
            else:
                # Save for reprint later
                self._save_for_reprint()

    def _save_for_reprint(self):
        """Save current reading data for reprint when paper is available."""
        if self._current_consumer is None:
            return

        reading = self.present_var.get()
        if not reading:
            return

        try:
            present = int(reading)
            previous = self._current_consumer["previous_reading"]
            consumption = present - previous
            exception = self.exception_var.get()
            is_flagged = (consumption > HIGH_CONSUMPTION_THRESHOLD) or (exception != "None")

            # Save to database first
            reading_id = save_reading(self._current_consumer["id"], present, consumption, exception, is_flagged)
            self._save_to_sync_layer(self._current_consumer["id"], present, consumption, exception, is_flagged)

            # Store for reprint
            self._last_receipt_data = {
                "consumer": dict(self._current_consumer),
                "reading_id": reading_id,
                "present": present,
                "previous": previous,
                "consumption": consumption,
                "exception": exception,
                "reader_name": self._current_user["name"] if self._current_user else "Field Reader",
                "timestamp": time.time()
            }
            self._current_consumer["previous_reading"] = present

            messagebox.showinfo("Saved for Reprint",
                "Reading saved successfully.\n\nYou can reprint this receipt once the paper issue is resolved.")
            self._refresh_zone_stats()
            self._clear_consumer_details()
            self.search_var.set("")

        except ValueError:
            messagebox.showerror("Error", "Invalid reading value.")

    def _show_saving_overlay(self):
        self._spawn_overlay("Saving...", "Saving to database", self._do_save_to_db)

    def _do_save_to_db(self):
        """Run on a background thread – saves the reading to SQLite."""
        consumer = self._current_consumer
        present = int(self.present_var.get())
        previous = consumer["previous_reading"]
        consumption = present - previous
        exception = self.exception_var.get()
        is_flagged = (consumption > HIGH_CONSUMPTION_THRESHOLD) or (exception != "None")
        reading_id = save_reading(consumer["id"], present, consumption, exception, is_flagged)
        self._save_to_sync_layer(consumer["id"], present, consumption, exception, is_flagged)
        # Update the cached consumer so subsequent validations use the new previous
        self._current_consumer["_original_previous"] = self._current_consumer["previous_reading"]
        self._current_consumer["previous_reading"] = present
        # Store for potential reprint
        self._last_receipt_data = {
            "consumer": dict(consumer),
            "reading_id": reading_id,
            "present": present,
            "previous": previous,
            "consumption": consumption,
            "exception": exception,
            "reader_name": self._current_user["name"] if self._current_user else "Field Reader",
            "timestamp": time.time()
        }
        self.after(0, self._refresh_zone_stats)
        self.after(0, self._proceed_to_printing)

    def _save_to_sync_layer(self, consumer_id: int, present: int, consumption: int, exception: str, is_flagged: bool):
        """Mirror local save to sync layer (online write or offline queue)."""
        if not self._auto_push_enabled.get():
            self.after(0, lambda: self._refresh_sync_status_ui("auto-push disabled"))
            return
        if not self._sync_dal:
            return
        consumer = self._current_consumer or {}
        payload = {
            "consumer_id": consumer_id,
            "acct_no": consumer.get("acct_no"),
            "meter_no": consumer.get("meter_no"),
            "zone_name": consumer.get("zone_name"),
            "classification_id": consumer.get("classification_id"),
            "classification_name": consumer.get("classification_name"),
            "minimum_cubic": consumer.get("minimum_cubic"),
            "minimum_rate": consumer.get("minimum_rate"),
            "excess_rate_per_cubic": consumer.get("excess_rate_per_cubic"),
            "due_days": consumer.get("due_days"),
            "late_fee": consumer.get("late_fee"),
            "amount_due": consumer.get("amount_due"),
            "due_date": consumer.get("due_date"),
            "penalty": consumer.get("penalty"),
            "previous_penalty": consumer.get("previous_penalty"),
            "total_after_due_date": consumer.get("total_after_due_date"),
            "bill_status": consumer.get("bill_status"),
            "previous_reading": consumer.get("previous_reading"),
            "present_reading": present,
            "consumption": consumption,
            "exception": exception,
            "is_flagged": bool(is_flagged),
            "reading_date": datetime.now().date().isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._sync_dal.saveMeterReading(payload)
        except Exception as exc:
            self._sync_state = "Sync Failed"
            print(f"Sync layer save failed: {exc}")
        finally:
            self.after(0, self._refresh_sync_status_ui)

    def _proceed_to_printing(self):
        self._dismiss_overlay()
        self._spawn_overlay("Printing...", "Please wait", self._simulate_printing)

    def _receipt_entry_to_payload(self, entry):
        if not entry:
            return None
        timestamp = time.time()
        printed_at = entry.get("printed_at")
        if printed_at:
            try:
                timestamp = datetime.fromisoformat(str(printed_at).replace(" ", "T")).timestamp()
            except ValueError:
                pass
        return {
            "id": entry.get("id"),
            "consumer": {
                "id": entry.get("consumer_id"),
                "acct_no": entry.get("acct_no"),
                "name": entry.get("consumer_name"),
                "meter_no": entry.get("meter_no"),
                "zone_name": entry.get("zone_name"),
                "previous_reading": entry.get("present_reading"),
                "_original_previous": entry.get("previous_reading"),
            },
            "reading_id": entry.get("reading_id"),
            "present": entry.get("present_reading"),
            "previous": entry.get("previous_reading"),
            "consumption": entry.get("consumption"),
            "exception": entry.get("exception") or "None",
            "reader_name": entry.get("reader_name") or "Field Reader",
            "receipt_text": entry.get("receipt_text"),
            "timestamp": timestamp,
        }

    def _persist_receipt_print(self, consumer, previous, present, exception, reader_name, receipt_text, print_action, reading_id=None):
        consumption = present - previous
        saved_id = save_receipt_print(
            consumer["id"],
            receipt_text,
            previous,
            present,
            consumption,
            exception,
            reader_name,
            reading_id,
            print_action,
            consumer.get("acct_no"),
            consumer.get("name"),
            consumer.get("meter_no"),
            consumer.get("zone_name"),
        )
        self._last_receipt_data = {
            "id": saved_id,
            "consumer": dict(consumer),
            "reading_id": reading_id,
            "present": present,
            "previous": previous,
            "consumption": consumption,
            "exception": exception,
            "reader_name": reader_name,
            "receipt_text": receipt_text,
            "timestamp": time.time(),
        }
        return saved_id

    def _deliver_receipt(self, consumer, previous, present, exception, reader_name, reading_id=None, print_action="print", receipt_text=None):
        receipt_text = receipt_text or build_receipt_text(consumer, previous, present, exception, reader_name)
        self._persist_receipt_print(consumer, previous, present, exception, reader_name, receipt_text, print_action, reading_id)
        if can_use_system_printer():
            try:
                send_to_system_printer(receipt_text)
                return True
            except Exception as exc:
                messagebox.showwarning(
                    "Printer Error",
                    f"Unable to print to the GP58 over USB.\n\n{exc}\n\nShowing receipt preview instead.",
                )
        show_receipt(self, consumer, previous, present, exception, reader_name)
        return False

    def _simulate_printing(self):
        consumer = self._current_consumer
        present = int(self.present_var.get())
        previous = consumer["_original_previous"]
        exception = self.exception_var.get()
        reader_name = self._current_user["name"] if self._current_user else "Field Reader"
        reading_id = self._last_receipt_data.get("reading_id") if self._last_receipt_data else None
        self.after(0, self._dismiss_overlay)
        self.after(100, lambda: self._deliver_receipt(consumer, previous, present, exception, reader_name, reading_id, "print"))

    def _show_reprint_dialog(self):
        """Show dialog to reprint the last saved receipt."""
        if self._last_receipt_data is None:
            messagebox.showinfo("No Receipt", "No saved receipt available for reprint.")
            return

        # Check if paper is available
        if not self.status_bar.can_print():
            self._show_paper_error(self.status_bar.get_paper_status())
            return

        # Ask if user wants to reprint
        data = self._last_receipt_data
        consumer = data["consumer"]
        elapsed = int(time.time() - data["timestamp"])
        time_str = f"{elapsed}s ago" if elapsed < 60 else f"{elapsed // 60}m ago"

        result = messagebox.askyesno("Reprint Receipt",
            f"Reprint last receipt?\n\n"
            f"Consumer: {consumer['name']}\n"
            f"Meter: {consumer['meter_no']}\n"
            f"Saved: {time_str}")

        if result:
            latest_entry = get_latest_receipt_print(consumer["id"])
            receipt_text = latest_entry["receipt_text"] if latest_entry else data.get("receipt_text")
            reader_name = self._current_user["name"] if self._current_user else "Field Reader"
            self._deliver_receipt(
                consumer,
                data["previous"],
                data["present"],
                data["exception"],
                reader_name,
                latest_entry.get("reading_id") if latest_entry else data.get("reading_id"),
                "reprint",
                receipt_text,
            )

    def _spawn_overlay(self, title, subtitle, target_task):
        self.overlay = tk.Toplevel(self)
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.grab_set()
        wx, wy = self.winfo_rootx(), self.winfo_rooty()
        ww, wh = self.winfo_width(), self.winfo_height()
        self.overlay.geometry(f"{ww}x{wh}+{wx}+{wy}")
        ov = tk.Canvas(self.overlay, width=ww, height=wh, bg=OVERLAY_DIM, highlightthickness=0)
        ov.pack(fill="both", expand=True)
        ov.create_rectangle(0, 0, ww, wh, fill=OVERLAY_DIM, outline="")
        cx, cy = ww // 2, wh // 2
        bw, bh = 240, 180
        self._draw_rr(ov, cx-bw//2, cy-bh//2, cx+bw//2, cy+bh//2, 8, fill=WHITE, outline="")
        self._spinner_canvas = ov
        self._spinner_dots = []
        self._spinner_step = 0
        dr, sr = 4, 20
        for i in range(8):
            a = math.radians(i * 45 - 90)
            dx = cx + sr * math.cos(a)
            dy = (cy - 20) + sr * math.sin(a)
            dot = ov.create_oval(dx-dr, dy-dr, dx+dr, dy+dr, fill=BORDER_COLOR, outline="")
            self._spinner_dots.append(dot)
        ov.create_text(cx, cy + 25, text=title, font=(FONT_FAMILY, 14, "bold"), fill=DARK_TEXT)
        ov.create_text(cx, cy + 45, text=subtitle, font=(FONT_FAMILY, 9), fill=MID_TEXT)
        self._animate_spinner()
        threading.Thread(target=target_task, daemon=True).start()

    def _animate_spinner(self):
        if not hasattr(self, 'overlay') or not self.overlay.winfo_exists(): return
        for i, dot in enumerate(self._spinner_dots):
            offset = (self._spinner_step - i) % 8
            if   offset == 0: color = ACCENT_BLUE
            elif offset == 1: color = "#64B5F6"
            elif offset == 2: color = "#BBDEFB"
            else:              color = BORDER_COLOR
            self._spinner_canvas.itemconfigure(dot, fill=color)
        self._spinner_step += 1
        self._anim_id = self.after(120, self._animate_spinner)

    def _dismiss_overlay(self):
        if hasattr(self, '_anim_id'): self.after_cancel(self._anim_id)
        if hasattr(self, 'overlay') and self.overlay.winfo_exists():
            self.overlay.grab_release()
            self.overlay.destroy()

    def _show_success(self):
        self._dismiss_overlay()
        self.success_overlay = tk.Toplevel(self)
        self.success_overlay.overrideredirect(True)
        self.success_overlay.attributes("-topmost", True)
        self.success_overlay.grab_set()
        wx, wy = self.winfo_rootx(), self.winfo_rooty()
        ww, wh = self.winfo_width(), self.winfo_height()
        self.success_overlay.geometry(f"{ww}x{wh}+{wx}+{wy}")
        sc = tk.Canvas(self.success_overlay, width=ww, height=wh, bg=OVERLAY_DIM, highlightthickness=0)
        sc.pack(fill="both", expand=True)
        sc.create_rectangle(0, 0, ww, wh, fill=OVERLAY_DIM, outline="")
        cx, cy = ww // 2, wh // 2
        bw, bh = 260, 220
        self._draw_rr(sc, cx-bw//2, cy-bh//2, cx+bw//2, cy+bh//2, 8, fill=WHITE, outline="")
        cr = 28
        sc.create_oval(cx-cr, cy-55-cr, cx+cr, cy-55+cr, fill=SUCCESS_GREEN, outline="")
        sc.create_text(cx, cy-55, text="OK", font=(FONT_FAMILY, 16, "bold"), fill=WHITE)
        sc.create_text(cx, cy-5, text="Print Successful!", font=(FONT_FAMILY, 15, "bold"), fill=DARK_TEXT)
        sc.create_text(cx, cy+20, text="Receipt has been printed successfully.", font=(FONT_FAMILY, 9), fill=MID_TEXT)
        bx1, by1, bw2, bh2 = cx - 60, cy + 45, 120, 38
        ok_r = self._draw_rr(sc, bx1, by1, bx1+bw2, by1+bh2, 8, fill=PRIMARY_BLUE, outline="")
        ok_t = sc.create_text(cx, by1+bh2//2, text="OK", font=(FONT_FAMILY, 12, "bold"), fill=WHITE)
        for item in (ok_r, ok_t):
            sc.tag_bind(item, "<Button-1>", lambda e: self._dismiss_success())
        sc.bind("<Return>", lambda e: self._dismiss_success())
        sc.focus_set()

    def _dismiss_success(self):
        if hasattr(self, 'success_overlay') and self.success_overlay.winfo_exists():
            self.success_overlay.grab_release()
            self.success_overlay.destroy()

    @staticmethod
    def _draw_rr(canvas, x1, y1, x2, y2, r=12, **kw):
        pts = [
            x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
            x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
            x1, y2, x1, y2-r, x1, y1+r, x1, y1, x1+r, y1,
        ]
        return canvas.create_polygon(pts, smooth=True, **kw)


if __name__ == "__main__":
    app = MeterReaderApp()
    app.mainloop()

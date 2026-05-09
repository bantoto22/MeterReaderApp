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
import ctypes
import socket
import subprocess
from datetime import datetime, timezone
from PIL import Image, ImageTk
try:
    from .database import (
        init_db,
        search_consumer,
        search_consumers_by_zone,
        save_reading,
        get_zone_stats,
        get_all_zone_names,
        get_zone_consumers_with_status,
        replace_consumers_from_sync,
        authenticate_user,
        get_all_users,
        seed_default_users,
    )
    from .receipt import show_receipt
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
        replace_consumers_from_sync,
        authenticate_user,
        get_all_users,
        seed_default_users,
    )
    from receipt import show_receipt
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
BG_COLOR         = "#F0F2F5"
WHITE            = "#FFFFFF"
PRIMARY_BLUE     = "#1565C0"
HEADER_BLUE      = "#1565C0"
TAB_DARK         = "#1A2744"
TAB_BLUE         = "#1565C0"
ACCENT_BLUE      = "#2196F3"
DARK_TEXT         = "#1A1A2E"
MID_TEXT          = "#5A5A7A"
LIGHT_TEXT        = "#9E9EAF"
PLACEHOLDER_CLR  = "#B0B0C0"
BORDER_COLOR     = "#E0E3EA"
INPUT_BORDER     = "#CED4DA"
INPUT_FOCUS      = ACCENT_BLUE
INPUT_BG         = "#FAFBFC"
DARK_BTN         = "#1A2744"
DARK_HOVER       = "#2D2D4A"
OVERLAY_DIM      = "#1A1A2E"
SUCCESS_GREEN    = "#43A047"
SUCCESS_TEXT     = "#36EF45" 

# Consumption states
VALID_BG         = "#E8F5E9"
VALID_BORDER     = "#43A047"
VALID_TEXT        = "#2E7D32"
WARNING_BG       = "#FFF8E1"
WARNING_BORDER   = "#F9A825"
WARNING_TEXT      = "#E65100"
INVALID_BG       = "#FFEBEE"
INVALID_BORDER   = "#E53935"
INVALID_TEXT      = "#C62828"

DEVICE_WIDTH     = 480
DEVICE_HEIGHT    = 750  # Perfectly fitted to screen size
FONT_FAMILY      = "Montserrat"

HIGH_CONSUMPTION_THRESHOLD = 500

# --- Phone Status Bar Colors -------------------------------------------------
STATUS_BAR_BG = "#1A1A2E"
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
        # Header
        header = tk.Frame(self, bg=HEADER_BLUE, height=92)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="Meter Reader Login", font=(FONT_FAMILY, 18, "bold"),
                 bg=HEADER_BLUE, fg=WHITE).pack(expand=True)

        # Body area fills remaining screen and centers login form.
        body = tk.Frame(self, bg=BG_COLOR)
        body.pack(fill="both", expand=True)

        center_wrap = tk.Frame(body, bg=BG_COLOR)
        center_wrap.place(relx=0.5, rely=0.46, anchor="center")

        # Logo/Icon area
        icon_frame = tk.Frame(center_wrap, bg=BG_COLOR)
        icon_frame.pack(pady=(10, 18))

        # Draw a simple user icon using canvas
        icon_canvas = tk.Canvas(icon_frame, width=80, height=80, bg=BG_COLOR, highlightthickness=0)
        icon_canvas.pack()
        # Circle background
        icon_canvas.create_oval(5, 5, 75, 75, fill=PRIMARY_BLUE, outline="")
        # User silhouette
        icon_canvas.create_oval(30, 20, 50, 40, fill=WHITE, outline="")  # head
        icon_canvas.create_arc(20, 35, 60, 70, fill=WHITE, outline="", start=0, extent=180)  # body

        # Login form card
        form_card = tk.Frame(center_wrap, bg=WHITE, bd=1, relief="flat", highlightthickness=1, highlightbackground=BORDER_COLOR)
        form_card.pack(padx=24, pady=8, fill="x")
        form_frame = tk.Frame(form_card, bg=WHITE)
        form_frame.pack(fill="x", padx=22, pady=18)

        # Username
        tk.Label(form_frame, text="Username", font=(FONT_FAMILY, 13, "bold"),
                 bg=WHITE, fg=DARK_TEXT).pack(anchor="w", pady=(0, 6))

        self._username_var = tk.StringVar()
        self._username_entry = RoundedEntry(form_frame, placeholder="Enter username...",
                                          height=74, radius=12, font=(FONT_FAMILY, 18),
                                          textvariable=self._username_var)
        self._username_entry.pack(fill="x", pady=(0, 14))

        # Password
        tk.Label(form_frame, text="Password", font=(FONT_FAMILY, 13, "bold"),
                 bg=WHITE, fg=DARK_TEXT).pack(anchor="w", pady=(0, 6))

        self._password_var = tk.StringVar()
        self._password_entry = RoundedEntry(form_frame, placeholder="Enter password...",
                                            height=74, radius=12, font=(FONT_FAMILY, 18),
                                            textvariable=self._password_var)
        self._password_entry.entry.config(show="•")
        self._password_entry.pack(fill="x", pady=(0, 24))

        # Error message label
        self._error_label = tk.Label(form_frame, text="", font=(FONT_FAMILY, 10),
                                     bg=WHITE, fg=INVALID_TEXT)
        self._error_label.pack(pady=(0, 10))

        # Login button
        login_btn = tk.Button(form_frame, text="LOGIN", font=(FONT_FAMILY, 20, "bold"),
                             bg=TAB_DARK, fg=WHITE, activebackground=DARK_HOVER,
                             activeforeground=WHITE, relief="flat", bd=0,
                             cursor="hand2", pady=16, command=self._attempt_login)
        login_btn.pack(fill="x", ipady=14)

        login_btn.bind("<Enter>", lambda e: e.widget.config(bg=DARK_HOVER))
        login_btn.bind("<Leave>", lambda e: e.widget.config(bg=TAB_DARK))

        # Bind Enter key
        self._password_entry.entry.bind("<Return>", lambda e: self._attempt_login())
        self._username_entry.entry.bind("<Return>", lambda e: self._password_entry.entry.focus())

        # Bottom loading/info panel (replaces Available Users list).
        hint_frame = tk.Frame(body, bg=BG_COLOR)
        hint_frame.pack(side="bottom", pady=(8, 16))
        self._loading_title_label = tk.Label(
            hint_frame,
            text="Loading data and sync services...",
            font=(FONT_FAMILY, 10, "bold"),
            bg=BG_COLOR,
            fg=MID_TEXT,
        )
        self._loading_title_label.pack()
        self._loading_detail_label = tk.Label(
            hint_frame,
            text="Please wait",
            font=(FONT_FAMILY, 9),
            bg=BG_COLOR,
            fg=LIGHT_TEXT,
        )
        self._loading_detail_label.pack(pady=(2, 0))
        self._loading_hint_frame = hint_frame

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


# --- GroupCard Container -----------------------------------------------------
class GroupCard(tk.Canvas):
    """A minimal Canvas container that renders a rounded flat card background."""

    def __init__(self, parent, radius=8, bg_color=WHITE, outline=BORDER_COLOR, **kwargs):
        self._radius = radius
        self._bg_color = bg_color
        self._outline = outline
        
        super().__init__(parent, highlightthickness=0, bg=parent["bg"], **kwargs)
        
        self.inner_frame = tk.Frame(self, bg=self._bg_color)
        self._window = self.create_window(radius, radius, anchor="nw", window=self.inner_frame)
        self.inner_frame.bind("<Configure>", self._on_frame_configure)
        self.bind("<Configure>", self._redraw)
        
    def _on_frame_configure(self, event):
        self.configure(height=event.height + 2 * self._radius)
        self._redraw()
        
    def _redraw(self, event=None):
        self.delete("bg_shape")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1 or h <= 1: return
        r = self._radius
        self.itemconfig(self._window, width=w - 2 * r)
        self._draw_rr(1, 1, w - 1, h - 1, r, fill=self._bg_color, outline=self._outline, width=1, tags="bg_shape")
        self.tag_lower("bg_shape")
        
    def _draw_rr(self, x1, y1, x2, y2, r, **kw):
        pts = [
            x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
            x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
            x1, y2, x1, y2-r, x1, y1+r, x1, y1, x1+r, y1,
        ]
        return self.create_polygon(pts, smooth=True, **kw)


# --- Main Application --------------------------------------------------------
class MeterReaderApp(tk.Tk):
    def __init__(self):
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
        self._last_receipt_data = None
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
                if self._sync_dal.is_online():
                    self._hydrate_local_consumers_from_sync()
                    self.after(0, self._refresh_zone_stats)
                    self.after(0, lambda: self._refresh_sync_status_ui("auto-pull complete"))
                else:
                    self.after(0, lambda: self._refresh_sync_status_ui("offline"))
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
        self._keyboard_content.pack(fill="both", expand=True, padx=10, pady=10)

    def _keyboard_btn(self, parent, text, command, expand=False, bg_color=TAB_DARK, fg_color=WHITE):
        btn = tk.Button(
            parent,
            text=text,
            font=(FONT_FAMILY, self._touch_font_base, "bold"),
            bg=bg_color,
            fg=fg_color,
            activebackground="#354766",
            activeforeground=fg_color,
            relief="flat",
            bd=0,
            cursor="hand2",
            command=command,
            padx=6,
            pady=4,
            highlightthickness=0,
        )
        btn.pack(side="left", fill="both", expand=expand, padx=4, pady=4, ipady=10)
        return btn

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

        for row_idx, row_keys in enumerate(rows):
            row = tk.Frame(self._keyboard_content, bg="#1C2434")
            row.pack(fill="x")
            if self._keyboard_mode != "numeric" and row_idx == 2:
                self._keyboard_btn(
                    row,
                    "↑" if not self._keyboard_caps else "↑ ON",
                    self._toggle_keyboard_caps,
                    expand=False,
                    bg_color="#334360" if self._keyboard_caps else "#253048",
                    fg_color="#66C6FF",
                )
            for key_char in row_keys:
                label = key_char.upper() if self._keyboard_caps else key_char
                value = key_char.upper() if self._keyboard_caps else key_char
                self._keyboard_btn(row, label, lambda c=value: self._insert_key(c), expand=True, bg_color="#253048", fg_color="#66C6FF")
            if self._keyboard_mode != "numeric" and row_idx == 2:
                self._keyboard_btn(row, "⌫", self._backspace_key, expand=False, bg_color="#2B3550", fg_color="#66C6FF")

        if self._keyboard_mode == "numeric":
            bottom_row = tk.Frame(self._keyboard_content, bg="#1C2434")
            bottom_row.pack(fill="x")
            self._keyboard_btn(bottom_row, "ABC", self._toggle_keyboard_mode, expand=True, bg_color="#253048", fg_color="#66C6FF")
            self._keyboard_btn(bottom_row, "0", lambda: self._insert_key("0"), expand=True, bg_color="#253048", fg_color="#66C6FF")
            self._keyboard_btn(bottom_row, "⌫", self._backspace_key, expand=True, bg_color="#2B3550", fg_color="#66C6FF")

        if self._keyboard_mode != "numeric":
            action_row = tk.Frame(self._keyboard_content, bg="#1C2434")
            action_row.pack(fill="x")
            self._keyboard_btn(action_row, "123", self._toggle_keyboard_mode, expand=False, bg_color="#253048", fg_color="#66C6FF")
            self._keyboard_btn(action_row, "space", lambda: self._insert_key(" "), expand=True, bg_color="#2C374F", fg_color="#66C6FF")

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

    def _build_app_content(self):
        """Build the main application content (shown after login)."""
        # -- Tab Navigation -----------------------------------------------
        tab_bar = tk.Frame(self.app_content, bg=TAB_DARK, height=60)
        tab_bar.pack(fill="x")
        tab_bar.pack_propagate(False)

        self.entry_tab_btn = tk.Button(
            tab_bar, text="Meter Entry", font=(FONT_FAMILY, self._touch_font_base, "bold"),
            bg=TAB_DARK, fg=WHITE, relief="flat", bd=0, cursor="hand2",
            activebackground=TAB_DARK, activeforeground=WHITE,
            command=lambda: self._switch_page("meter_entry"))
        self.entry_tab_btn.pack(side="left", fill="both", expand=True)

        self.progress_tab_btn = tk.Button(
            tab_bar, text="Progress", font=(FONT_FAMILY, self._touch_font_base, "bold"),
            bg=TAB_BLUE, fg=WHITE, relief="flat", bd=0, cursor="hand2",
            activebackground=TAB_BLUE, activeforeground=WHITE,
            command=lambda: self._switch_page("progress"))
        self.progress_tab_btn.pack(side="left", fill="both", expand=True)

        self.settings_tab_btn = tk.Button(
            tab_bar, text="Settings", font=(FONT_FAMILY, self._touch_font_base, "bold"),
            bg=TAB_BLUE, fg=WHITE, relief="flat", bd=0, cursor="hand2",
            activebackground=TAB_BLUE, activeforeground=WHITE,
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
        
        # Get available zones
        zones = get_all_zone_names()
        if not zones:
            return
        
        # Create dropdown popup
        self._zone_dropdown_popup = tk.Toplevel(self)
        self._zone_dropdown_popup.overrideredirect(True)
        self._zone_dropdown_popup.configure(bg=WHITE)
        
        # Position dropdown below the zone label
        label_x = self._active_zone_label.winfo_rootx()
        label_y = self._active_zone_label.winfo_rooty()
        label_height = self._active_zone_label.winfo_height()
        
        # Create dropdown content
        dropdown_frame = tk.Frame(self._zone_dropdown_popup, bg=BORDER_COLOR, bd=1)
        dropdown_frame.pack(fill="both", expand=True)
        
        current_zone = self._current_zone.get()
        
        for zone in zones:
            # Highlight current zone
            is_current = zone == current_zone
            bg_color = PRIMARY_BLUE if is_current else WHITE
            fg_color = WHITE if is_current else DARK_TEXT
            font_style = (FONT_FAMILY, 11, "bold") if is_current else (FONT_FAMILY, 11)
            
            zone_row = tk.Label(dropdown_frame, text=zone, font=font_style,
                               bg=bg_color, fg=fg_color, anchor="w", padx=12, pady=8,
                               cursor="hand2")
            zone_row.pack(fill="x")
            
            # Bind click to select zone
            zone_row.bind("<Button-1>", lambda e, z=zone: self._select_zone(z))
            
            # Hover effects
            if not is_current:
                zone_row.bind("<Enter>", lambda e, row=zone_row: row.config(bg="#F0F2F5"))
                zone_row.bind("<Leave>", lambda e, row=zone_row: row.config(bg=WHITE))
        
        # Calculate width based on content
        dropdown_width = max(120, self._active_zone_label.winfo_width())
        
        self._zone_dropdown_popup.geometry(f"{dropdown_width}x{len(zones) * 36 + 2}+{label_x}+{label_y + label_height}")
        
        # Close dropdown when clicking outside
        self._zone_dropdown_popup.bind("<FocusOut>", lambda e: self._hide_zone_dropdown())
        self._zone_dropdown_popup.focus_set()
    
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
            self.entry_tab_btn.config(bg=TAB_DARK, activebackground=TAB_DARK)
            self.progress_tab_btn.config(bg=TAB_BLUE, activebackground=TAB_BLUE)
            self.settings_tab_btn.config(bg=TAB_BLUE, activebackground=TAB_BLUE)
            self.meter_entry_frame.tkraise()
        elif page_name == "progress":
            self.entry_tab_btn.config(bg=TAB_BLUE, activebackground=TAB_BLUE)
            self.progress_tab_btn.config(bg=TAB_DARK, activebackground=TAB_DARK)
            self.settings_tab_btn.config(bg=TAB_BLUE, activebackground=TAB_BLUE)
            self.progress_frame.tkraise()
            self._animate_progress_bar()
            # Hide autocomplete when switching to progress tab
            self._hide_autocomplete()
        else:
            self.entry_tab_btn.config(bg=TAB_BLUE, activebackground=TAB_BLUE)
            self.progress_tab_btn.config(bg=TAB_BLUE, activebackground=TAB_BLUE)
            self.settings_tab_btn.config(bg=TAB_DARK, activebackground=TAB_DARK)
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
        header_bg = tk.Frame(self.meter_entry_frame, bg=HEADER_BLUE, height=48)
        header_bg.pack(fill="x")
        header_bg.pack_propagate(False)

        header_content = tk.Frame(header_bg, bg=HEADER_BLUE)
        header_content.pack(fill="both", expand=True, padx=14, pady=4)

        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "images", "SLR logo 1.png")
        if os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path)
                logo_img.thumbnail((32, 32), Image.Resampling.LANCZOS)
                self.logo_photo = ImageTk.PhotoImage(logo_img)
                tk.Label(header_content, image=self.logo_photo, bg=HEADER_BLUE).pack(side="left", padx=(0, 6))
            except Exception:
                pass

        tk.Label(header_content, text="Water Meter Reading System", font=(FONT_FAMILY, 12, "bold"), bg=HEADER_BLUE, fg=WHITE).pack(side="left", anchor="w")

        # Profile icon in header
        self._profile_btn = tk.Label(header_content, text="User", font=(FONT_FAMILY, 11, "bold"),
                                     bg=HEADER_BLUE, fg=WHITE, cursor="hand2")
        self._profile_btn.pack(side="right")
        self._profile_btn.bind("<Button-1>", lambda e, b=self._profile_btn: self._show_profile_menu(b))

        # -- Main Content Container (No Scrollbar) ------------------------
        main = tk.Frame(self.meter_entry_frame, bg=BG_COLOR)
        main.pack(fill="both", expand=True)

        px = 18

        # -- Search Section -----------------------------------------------
        search_section = tk.Frame(main, bg=BG_COLOR)
        search_section.pack(fill="x", padx=px, pady=(10, 4))

        search_header = tk.Frame(search_section, bg=BG_COLOR)
        search_header.pack(fill="x", pady=0)

        tk.Label(search_header, text="Search by Meter No.", font=(FONT_FAMILY, 11, "bold"), fg=DARK_TEXT, bg=BG_COLOR).pack(side="left")

        # Zone selector button (styled like a button)
        self._zone_btn_frame = tk.Frame(search_header, bg=PRIMARY_BLUE, padx=2, pady=2)
        self._zone_btn_frame.pack(side="right")
        
        self._active_zone_label = tk.Label(self._zone_btn_frame, text=self._current_zone.get(),
                                           font=(FONT_FAMILY, 12, "bold"),
                                           fg=WHITE, bg=PRIMARY_BLUE,
                                           padx=12, pady=4,
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
        self.search_input = RoundedEntry(search_section, placeholder="Type 001, 002...", height=56, radius=10, font=(FONT_FAMILY, self._touch_font_base + 1), textvariable=self.search_var)
        self.search_input.pack(fill="x", pady=(2, 0))
        self.search_input.entry.bind("<Return>", self._on_search)
        self.search_input.entry.bind("<KeyRelease>", self._on_search_key)
        self.search_input.entry.bind("<FocusOut>", self._schedule_hide_autocomplete)

        search_mode_row = tk.Frame(search_section, bg=BG_COLOR)
        search_mode_row.pack(fill="x", pady=(4, 0))
        tk.Checkbutton(
            search_mode_row,
            text="Unread only",
            variable=self._search_unread_only,
            bg=BG_COLOR,
            fg=MID_TEXT,
            activebackground=BG_COLOR,
            activeforeground=DARK_TEXT,
            selectcolor=WHITE,
            font=(FONT_FAMILY, 10, "bold"),
            highlightthickness=0,
            bd=0,
            command=self._on_search_mode_changed,
        ).pack(side="left")

        sync_row = tk.Frame(main, bg=BG_COLOR)
        sync_row.pack(fill="x", padx=px, pady=(2, 4))
        self._sync_status_label = tk.Label(
            sync_row, text="Sync: Offline", font=(FONT_FAMILY, 10, "bold"), fg=MID_TEXT, bg=BG_COLOR
        )
        self._sync_status_label.pack(side="left")
        self._sync_pending_label = tk.Label(
            sync_row, text="Pending: 0", font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=BG_COLOR
        )
        self._sync_pending_label.pack(side="left", padx=(10, 0))
        self._sync_target_label = None
        self._sync_backup_label = None
        self._sync_last_label = None
        self._sync_now_btn = tk.Button(
            sync_row,
            text="Sync Now",
            font=(FONT_FAMILY, 10, "bold"),
            bg=PRIMARY_BLUE,
            fg=WHITE,
            activebackground=ACCENT_BLUE,
            activeforeground=WHITE,
            relief="flat",
            bd=0,
            cursor="hand2",
            command=self._on_manual_sync_now,
            padx=10,
            pady=6,
        )
        self._sync_now_btn.pack(side="right")
        self._sync_log_btn = None

        # -- Grouped Detail Card ------------------------------------------
        self.group_card = GroupCard(main, radius=10, bg_color=WHITE)
        self.group_card.pack(fill="x", padx=px, pady=(2, 2))
        card = self.group_card.inner_frame

        # -- Consumer Details Section -------------------------------------
        details_section = tk.Frame(card, bg=WHITE)
        details_section.pack(fill="x", pady=(0, 0))

        tk.Label(details_section, text="Consumer Details", font=(FONT_FAMILY, 12, "bold"), fg=DARK_TEXT, bg=WHITE).pack(anchor="w", pady=(0, 2))

        self._detail_labels = {}
        for label in ["Account No.", "Name", "Previous"]:
            row = tk.Frame(details_section, bg=WHITE)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE).pack(side="left")
            val_lbl = tk.Label(row, text="-", font=(FONT_FAMILY, 12, "bold"), fg=DARK_TEXT, bg=WHITE)
            val_lbl.pack(side="right")
            self._detail_labels[label] = val_lbl

        # Compact separator
        tk.Frame(card, height=1, bg=BORDER_COLOR).pack(fill="x", pady=2)

        # -- Present Reading Section --------------------------------------
        ri = tk.Frame(card, bg=WHITE)
        ri.pack(fill="x", pady=0)

        tk.Label(ri, text="Present Reading", font=(FONT_FAMILY, 12, "bold"), fg=DARK_TEXT, bg=WHITE).pack(anchor="w", pady=(0, 2))

        vcmd = (self.register(self._validate_numeric), "%P")

        self.present_var = tk.StringVar()
        self.reading_input = RoundedEntry(
            ri, placeholder="Enter current reading...",
            height=56, radius=10, bg=WHITE,
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
        cons_row.pack(fill="x", pady=(2, 0))

        tk.Label(cons_row, text="Consumption", font=(FONT_FAMILY, 11, "bold"), fg=DARK_TEXT, bg=WHITE).pack(side="left")

        cons_right = tk.Frame(cons_row, bg=WHITE)
        cons_right.pack(side="right")

        self._cons_title_label = tk.Label(cons_right, text="-", font=(FONT_FAMILY, 14, "bold"), fg=LIGHT_TEXT, bg=WHITE)
        self._cons_title_label.pack(anchor="e")

        self._cons_message_label = tk.Label(cons_right, text="-", font=(FONT_FAMILY, 9), fg=LIGHT_TEXT, bg=WHITE)
        self._cons_message_label.pack(anchor="e")

        self.present_var.trace_add("write", self._update_consumption)

        tk.Frame(card, height=1, bg=BORDER_COLOR).pack(fill="x", pady=2)

        # -- Exception Section --------------------------------------------
        ei = tk.Frame(card, bg=WHITE)
        ei.pack(fill="x", pady=0)

        tk.Label(ei, text="Exception", font=(FONT_FAMILY, 11, "bold"), fg=DARK_TEXT, bg=WHITE).pack(anchor="w", pady=(0, 2))

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
        btn_wrapper.pack(fill="x", padx=px, pady=(0, 4))

        self.print_btn = tk.Button(
            btn_wrapper, text="PRINT",
            font=(FONT_FAMILY, 24, "bold"),
            bg=TAB_DARK, fg=WHITE,
            activebackground=DARK_HOVER, activeforeground=WHITE,
            relief="flat", bd=0, cursor="hand2",
            highlightthickness=0, command=self._on_print)
        self.print_btn.pack(fill="x", ipady=26)

        self.print_btn.bind("<Enter>", lambda e: e.widget.config(bg=DARK_HOVER))
        self.print_btn.bind("<Leave>", lambda e: e.widget.config(bg=TAB_DARK))
        self.print_btn.bind("<ButtonPress-1>", lambda e: e.widget.config(bg="#0F1A30"), add="+")
        self.print_btn.bind("<ButtonRelease-1>", lambda e: e.widget.config(bg=DARK_HOVER), add="+")

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
        self.reprint_btn.pack(fill="x", ipady=18)

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

        header_bg = tk.Frame(self.progress_frame, bg=HEADER_BLUE, height=48)
        header_bg.pack(fill="x")
        header_bg.pack_propagate(False)

        header_content = tk.Frame(header_bg, bg=HEADER_BLUE)
        header_content.pack(fill="both", expand=True, padx=14, pady=4)

        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "images", "SLR logo 1.png")
        if os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path)
                logo_img.thumbnail((32, 32), Image.Resampling.LANCZOS)
                self._progress_logo = ImageTk.PhotoImage(logo_img)
                tk.Label(header_content, image=self._progress_logo, bg=HEADER_BLUE).pack(side="left", padx=(0, 6))
            except Exception:
                pass

        tk.Label(header_content, text="Water Meter Reading System", font=(FONT_FAMILY, 12, "bold"), bg=HEADER_BLUE, fg=WHITE).pack(side="left", anchor="w")

        # Profile icon in header
        self._profile_btn2 = tk.Label(header_content, text="User", font=(FONT_FAMILY, 11, "bold"),
                                      bg=HEADER_BLUE, fg=WHITE, cursor="hand2")
        self._profile_btn2.pack(side="right")
        self._profile_btn2.bind("<Button-1>", lambda e, b=self._profile_btn2: self._show_profile_menu(b))

        # -- Main Content Container (wrapped in _progress_content for showing/hiding) ------------------------
        self._progress_content = tk.Frame(self.progress_frame, bg=BG_COLOR)
        self._progress_content.pack(fill="both", expand=True)
        
        main = tk.Frame(self._progress_content, bg=BG_COLOR)
        main.pack(fill="both", expand=True)

        px = 18

        # -- Assigned Zone Section ----------------------------------------
        zi = tk.Frame(main, bg=BG_COLOR)
        zi.pack(fill="x", padx=px, pady=(12, 6))

        tk.Label(zi, text="Assigned Zone", font=(FONT_FAMILY, 11, "bold"), fg=DARK_TEXT, bg=BG_COLOR).pack(anchor="w", pady=(0, 4))

        self._zone_combo = ttk.Combobox(zi, textvariable=self._current_zone,
                                   values=get_all_zone_names(),
                                   state="readonly", font=(FONT_FAMILY, 12, "bold"),
                                   style="Figma.TCombobox")
        self._zone_combo.pack(fill="x", ipady=4)
        self._zone_combo.bind("<<ComboboxSelected>>", self._on_zone_change)

        # -- Today's Progress Card (Blue) ---------------------------------
        self._progress_canvas = tk.Canvas(main, bg=BG_COLOR, highlightthickness=0, height=280)
        self._progress_canvas.pack(fill="x", padx=px, pady=(6, 4))

        # -- Zone Info Card (White) ---------------------------------------
        self._zone_info_canvas = tk.Canvas(main, bg=BG_COLOR, highlightthickness=0, height=130)
        self._zone_info_canvas.pack(fill="x", padx=px, pady=(4, 16))

        self._zone_info_canvas.bind("<Configure>", self._redraw_zone_card)
        self._progress_canvas.bind("<Configure>", self._redraw_progress_card)

    def _build_settings_page(self):
        self.settings_frame = tk.Frame(self.pages_container, bg=BG_COLOR)
        self.settings_frame.grid(row=0, column=0, sticky="nsew")

        header_bg = tk.Frame(self.settings_frame, bg=HEADER_BLUE, height=48)
        header_bg.pack(fill="x")
        header_bg.pack_propagate(False)
        tk.Label(
            header_bg,
            text="Settings",
            font=(FONT_FAMILY, 14, "bold"),
            bg=HEADER_BLUE,
            fg=WHITE,
        ).pack(expand=True)

        main = tk.Frame(self.settings_frame, bg=BG_COLOR)
        main.pack(fill="both", expand=True, padx=18, pady=12)

        card = GroupCard(main, radius=10, bg_color=WHITE)
        card.pack(fill="x", pady=(0, 8))
        inner = card.inner_frame

        tk.Label(inner, text="Sync Diagnostics", font=(FONT_FAMILY, 12, "bold"), fg=DARK_TEXT, bg=WHITE).pack(anchor="w")
        self._settings_sync_status = tk.Label(inner, text="Sync: Offline", font=(FONT_FAMILY, 11, "bold"), fg=MID_TEXT, bg=WHITE, anchor="w")
        self._settings_sync_status.pack(fill="x", pady=(6, 0))
        self._settings_pending_label = tk.Label(inner, text="Pending: 0", font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE, anchor="w")
        self._settings_pending_label.pack(fill="x", pady=(2, 0))
        self._sync_target_label = tk.Label(inner, text="Save Target: Local SQLite only", font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE, anchor="w")
        self._sync_target_label.pack(fill="x", pady=(2, 0))
        self._sync_backup_label = tk.Label(inner, text="Backup: Not configured", font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE, anchor="w")
        self._sync_backup_label.pack(fill="x", pady=(2, 0))
        self._sync_last_label = tk.Label(inner, text="Last Sync: Never", font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE, anchor="w")
        self._sync_last_label.pack(fill="x", pady=(2, 0))
        self._pull_mirror_label = tk.Label(inner, text="Last pull mirrored: 0 records", font=(FONT_FAMILY, 10), fg=MID_TEXT, bg=WHITE, anchor="w")
        self._pull_mirror_label.pack(fill="x", pady=(2, 0))

        sync_cfg = tk.Frame(inner, bg=WHITE)
        sync_cfg.pack(fill="x", pady=(8, 2))
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
        ).pack(anchor="w")
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
        ).pack(anchor="w", pady=(4, 0))

        interval_row = tk.Frame(inner, bg=WHITE)
        interval_row.pack(fill="x", pady=(6, 2))
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
        self._pull_interval_entry.pack(side="left", padx=(8, 0))
        self._pull_interval_entry.bind("<FocusOut>", lambda e: self._on_sync_config_changed())
        self._pull_interval_entry.bind("<Return>", lambda e: self._on_sync_config_changed())

        btn_row = tk.Frame(main, bg=BG_COLOR)
        btn_row.pack(fill="x")
        self._settings_sync_now_btn = tk.Button(
            btn_row,
            text="Sync Now",
            font=(FONT_FAMILY, 10, "bold"),
            bg=PRIMARY_BLUE,
            fg=WHITE,
            activebackground=ACCENT_BLUE,
            activeforeground=WHITE,
            relief="flat",
            bd=0,
            cursor="hand2",
            command=self._on_manual_sync_now,
            padx=10,
            pady=8,
        )
        self._settings_sync_now_btn.pack(side="left")

        self._sync_log_btn = tk.Button(
            btn_row,
            text="View Logs",
            font=(FONT_FAMILY, 10, "bold"),
            bg=TAB_DARK,
            fg=WHITE,
            activebackground=DARK_HOVER,
            activeforeground=WHITE,
            relief="flat",
            bd=0,
            cursor="hand2",
            command=self._show_sync_logs,
            padx=10,
            pady=8,
        )
        self._sync_log_btn.pack(side="left", padx=(8, 0))

        # Wi-Fi configuration
        wifi_card = GroupCard(main, radius=10, bg_color=WHITE)
        wifi_card.pack(fill="x", pady=(10, 0))
        wifi_inner = wifi_card.inner_frame
        tk.Label(wifi_inner, text="Connectivity", font=(FONT_FAMILY, 12, "bold"), fg=DARK_TEXT, bg=WHITE).pack(anchor="w")
        tk.Label(
            wifi_inner,
            text="Open system Wi-Fi settings to change network connection.",
            font=(FONT_FAMILY, 10),
            fg=MID_TEXT,
            bg=WHITE,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(4, 8))
        tk.Button(
            wifi_inner,
            text="Open Wi-Fi Settings",
            font=(FONT_FAMILY, 10, "bold"),
            bg=PRIMARY_BLUE,
            fg=WHITE,
            activebackground=ACCENT_BLUE,
            activeforeground=WHITE,
            relief="flat",
            bd=0,
            cursor="hand2",
            command=self._open_wifi_settings,
            padx=10,
            pady=8,
        ).pack(anchor="w")

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

        self._draw_rr(c, 2, 2, w - 2, h - 2, 8, fill=WHITE, outline=BORDER_COLOR, width=1)
        c.create_text(22, 28, text=zone_name, font=(FONT_FAMILY, 20, "bold"), fill=PRIMARY_BLUE, anchor="w")
        c.create_text(22, 54, text=f"{total} households assigned", font=(FONT_FAMILY, 10), fill=MID_TEXT, anchor="w")
        c.create_text(22, 90, text=f"{pct}%", font=(FONT_FAMILY, 26, "bold"), fill=SUCCESS_TEXT, anchor="w")
        c.create_text(22, 115, text="Complete", font=(FONT_FAMILY, 10), fill=MID_TEXT, anchor="w")
        
        # Interactive Sync Button
        sync_bg = c.create_oval(w - 60, 10, w - 16, 54, fill=WHITE, outline=BORDER_COLOR, width=1, tags="sync_btn")
        sync_txt = c.create_text(w - 38, 30, text="SYNC", font=(FONT_FAMILY, 11, "bold"), fill=PRIMARY_BLUE, anchor="center", tags="sync_btn")
        
        c.tag_bind("sync_btn", "<Enter>", lambda e: c.itemconfig(sync_bg, fill="#E3F2FD"))
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

        self._draw_rr(c, 2, 2, w - 2, h - 2, 8, fill=PRIMARY_BLUE, outline="")
        cx = w // 2

        c.create_text(cx, 28, text="Today's Progress", font=(FONT_FAMILY, 12, "bold"), fill=WHITE)
        c.create_text(cx, 75, text=f"{read}/{total}", font=(FONT_FAMILY, 46, "bold"), fill=WHITE)
        c.create_text(cx, 115, text="Meters Read", font=(FONT_FAMILY, 11), fill="#B3D4FC")

        bar_x1, bar_x2 = 28, w - 28
        bar_width = bar_x2 - bar_x1
        bar_y, bar_h = 138, 18

        self._draw_rr(c, bar_x1, bar_y, bar_x2, bar_y + bar_h, 9, fill="#3A7BD5", outline="")
        filled_w = int(bar_width * frac)
        if filled_w > 18:
            self._draw_rr(c, bar_x1, bar_y, bar_x1 + filled_w, bar_y + bar_h, 9, fill=SUCCESS_TEXT, outline="")

        div_y = 175
        c.create_line(28, div_y, w - 28, div_y, fill="#5C9CE6", width=1, dash=(3, 3))

        c.create_text(w // 4, 215, text=str(remaining), font=(FONT_FAMILY, 32, "bold"), fill=WHITE)
        c.create_text(w // 4, 248, text="Remaining", font=(FONT_FAMILY, 10), fill="#B3D4FC")
        c.create_text(3 * w // 4, 215, text=str(flagged), font=(FONT_FAMILY, 32, "bold"), fill="#FFD54F")
        c.create_text(3 * w // 4, 248, text="Flagged", font=(FONT_FAMILY, 10), fill="#B3D4FC")
        
        # Click hint
        c.create_text(cx, h - 15, text="Tap for details", font=(FONT_FAMILY, 9), fill="#B3D4FC")
        
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
            show_receipt(self, consumer, data['previous'], 
                       data['present'], data['exception'],
                       self._current_user['name'] if self._current_user else "Field Reader")
    
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

    def _open_wifi_settings(self):
        """Open platform Wi-Fi settings for field reconfiguration."""
        try:
            system_name = platform.system()
            if system_name == "Windows":
                subprocess.Popen(["cmd", "/c", "start", "ms-settings:network-wifi"], shell=False)
                return
            if system_name == "Linux":
                # Raspberry Pi OS desktop commonly has this tool.
                if subprocess.call(["which", "nm-connection-editor"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                    subprocess.Popen(["nm-connection-editor"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
                if subprocess.call(["which", "nmtui"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                    subprocess.Popen(["x-terminal-emulator", "-e", "nmtui"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
                if subprocess.call(["which", "raspi-config"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                    subprocess.Popen(["x-terminal-emulator", "-e", "sudo raspi-config"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
            messagebox.showinfo("Wi-Fi Settings", "No supported Wi-Fi settings tool was found on this device.")
        except Exception as exc:
            messagebox.showerror("Wi-Fi Settings", f"Unable to open Wi-Fi settings:\n{exc}")

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
            save_reading(self._current_consumer["id"], present, consumption, exception, is_flagged)
            self._save_to_sync_layer(self._current_consumer["id"], present, consumption, exception, is_flagged)

            # Store for reprint
            self._last_receipt_data = {
                "consumer": dict(self._current_consumer),
                "present": present,
                "previous": previous,
                "exception": exception,
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
        save_reading(consumer["id"], present, consumption, exception, is_flagged)
        self._save_to_sync_layer(consumer["id"], present, consumption, exception, is_flagged)
        # Update the cached consumer so subsequent validations use the new previous
        self._current_consumer["_original_previous"] = self._current_consumer["previous_reading"]
        self._current_consumer["previous_reading"] = present
        # Store for potential reprint
        self._last_receipt_data = {
            "consumer": dict(consumer),
            "present": present,
            "previous": previous,
            "exception": exception,
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
        payload = {
            "consumer_id": consumer_id,
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

    def _simulate_printing(self):
        consumer = self._current_consumer
        present = int(self.present_var.get())
        previous = consumer["_original_previous"]
        exception = self.exception_var.get()
        # Get current user name for receipt
        reader_name = self._current_user["name"] if self._current_user else "Field Reader"
        self.after(0, self._dismiss_overlay)
        self.after(100, lambda: show_receipt(self, consumer, previous, present, exception, reader_name))

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
            reader_name = self._current_user["name"] if self._current_user else "Field Reader"
            show_receipt(self, consumer, data["previous"], data["present"], data["exception"], reader_name)

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

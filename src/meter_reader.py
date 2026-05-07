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
from PIL import Image, ImageTk
from database import init_db, search_consumer, search_consumers_by_zone, save_reading, get_zone_stats, get_all_zone_names, get_zone_consumers_with_status, authenticate_user, get_all_users, seed_default_users
from receipt import show_receipt

# ─── Load custom font (Montserrat) on Windows ────────────────────────────────
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


# ─── Color palette ────────────────────────────────────────────────────────────
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

# ─── Phone Status Bar Colors ─────────────────────────────────────────────────
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

# ─── Meter Reader Users ───────────────────────────────────────────────────────
# Users are now stored in the database (users table)
# Default users seeded on first run:
#   reader1 / pass123 - Juan Santos (MR-001)
#   reader2 / pass456 - Maria Cruz (MR-002)


# ─── Status Bar Widget (Phone-style) ─────────────────────────────────────────
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
            icon = "🖨"
            text = "OK"
        elif self._paper_status == "low":
            color = PAPER_LOW
            icon = "⚠"
            text = "LOW"
        elif self._paper_status == "out":
            color = PAPER_OUT
            icon = "✗"
            text = "NO PAPER"
        else:  # jam
            color = PAPER_JAM
            icon = "⚠"
            text = "JAM"

        self.create_text(x, cy, text=f"{icon} {text}", font=(FONT_FAMILY, 9, "bold"), fill=color, anchor="center")


# ─── Login Screen ────────────────────────────────────────────────────────────
class LoginScreen(tk.Frame):
    """Login screen for meter readers."""

    def __init__(self, parent, on_login_success, **kwargs):
        super().__init__(parent, bg=BG_COLOR, **kwargs)
        self._on_login_success = on_login_success
        self._build_ui()

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=HEADER_BLUE, height=80)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="Meter Reader Login", font=(FONT_FAMILY, 16, "bold"),
                 bg=HEADER_BLUE, fg=WHITE).pack(expand=True)

        # Logo/Icon area
        icon_frame = tk.Frame(self, bg=BG_COLOR)
        icon_frame.pack(pady=(30, 20))

        # Draw a simple user icon using canvas
        icon_canvas = tk.Canvas(icon_frame, width=80, height=80, bg=BG_COLOR, highlightthickness=0)
        icon_canvas.pack()
        # Circle background
        icon_canvas.create_oval(5, 5, 75, 75, fill=PRIMARY_BLUE, outline="")
        # User silhouette
        icon_canvas.create_oval(30, 20, 50, 40, fill=WHITE, outline="")  # head
        icon_canvas.create_arc(20, 35, 60, 70, fill=WHITE, outline="", start=0, extent=180)  # body

        # Login form
        form_frame = tk.Frame(self, bg=BG_COLOR)
        form_frame.pack(padx=40, pady=10)

        # Username
        tk.Label(form_frame, text="Username", font=(FONT_FAMILY, 11, "bold"),
                 bg=BG_COLOR, fg=DARK_TEXT).pack(anchor="w", pady=(0, 4))

        self._username_var = tk.StringVar()
        self._username_entry = RoundedEntry(form_frame, placeholder="Enter username...",
                                          height=44, radius=8, font=(FONT_FAMILY, 12),
                                          textvariable=self._username_var)
        self._username_entry.pack(fill="x", pady=(0, 12))

        # Password
        tk.Label(form_frame, text="Password", font=(FONT_FAMILY, 11, "bold"),
                 bg=BG_COLOR, fg=DARK_TEXT).pack(anchor="w", pady=(0, 4))

        self._password_var = tk.StringVar()
        self._password_entry = RoundedEntry(form_frame, placeholder="Enter password...",
                                            height=44, radius=8, font=(FONT_FAMILY, 12),
                                            textvariable=self._password_var)
        self._password_entry.entry.config(show="•")
        self._password_entry.pack(fill="x", pady=(0, 20))

        # Error message label
        self._error_label = tk.Label(form_frame, text="", font=(FONT_FAMILY, 10),
                                     bg=BG_COLOR, fg=INVALID_TEXT)
        self._error_label.pack(pady=(0, 10))

        # Login button
        login_btn = tk.Button(form_frame, text="LOGIN", font=(FONT_FAMILY, 14, "bold"),
                             bg=TAB_DARK, fg=WHITE, activebackground=DARK_HOVER,
                             activeforeground=WHITE, relief="flat", bd=0,
                             cursor="hand2", pady=12, command=self._attempt_login)
        login_btn.pack(fill="x")

        login_btn.bind("<Enter>", lambda e: e.widget.config(bg=DARK_HOVER))
        login_btn.bind("<Leave>", lambda e: e.widget.config(bg=TAB_DARK))

        # Bind Enter key
        self._password_entry.entry.bind("<Return>", lambda e: self._attempt_login())
        self._username_entry.entry.bind("<Return>", lambda e: self._password_entry.entry.focus())

        # Available users hint
        hint_frame = tk.Frame(self, bg=BG_COLOR)
        hint_frame.pack(pady=20)

        tk.Label(hint_frame, text="Available Users:", font=(FONT_FAMILY, 10, "bold"),
                 bg=BG_COLOR, fg=MID_TEXT).pack()

        try:
            users = get_all_users()
            for user in users:
                tk.Label(hint_frame, text=f"• {user['name']} ({user['username']})",
                         font=(FONT_FAMILY, 9), bg=BG_COLOR, fg=LIGHT_TEXT).pack()
        except Exception:
            pass  # If DB not initialized yet, show nothing

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


# ─── Rounded Entry Widget ────────────────────────────────────────────────────
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


# ─── GroupCard Container ─────────────────────────────────────────────────────
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


# ─── Main Application ────────────────────────────────────────────────────────
class MeterReaderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.update_idletasks()
        self._screen_width = self.winfo_screenwidth()
        self._screen_height = self.winfo_screenheight()

        # Initialise the database (creates tables + seeds on first run)
        init_db()
        seed_default_users()  # Ensure default users exist

        self.title("Water Meter Reader")
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))
        self.configure(bg=BG_COLOR)

        self._current_page = "meter_entry"
        self._current_zone = tk.StringVar(value="Zone 1")
        self._shake_after_ids = []
        self._progress_anim_fraction = 0.0
        self._progress_anim_id = None

        # Currently loaded consumer from DB (None until a search is done)
        self._current_consumer = None
        # Cache zone stats from DB
        self._zones_data = get_zone_stats()
        # Autocomplete state
        self._autocomplete_popup = None
        self._autocomplete_results = []
        self._zone_dropdown_popup = None

        # Current logged-in user
        self._current_user = None

        # Last receipt data for reprint workflow
        self._last_receipt_data = None

        # Build the UI
        self._build_ui()

    def _build_ui(self):
        # ── Status Bar (Phone-style) ─────────────────────────────────────
        self.status_bar = StatusBar(self, height=28)
        self.status_bar.pack(fill="x")

        # ── Main Container ───────────────────────────────────────────────
        self.main_container = tk.Frame(self, bg=BG_COLOR)
        self.main_container.pack(fill="both", expand=True)
        self.main_container.bind("<Configure>", self._on_main_container_resize)

        # Centered content viewport for portrait touchscreens.
        self.content_viewport = tk.Frame(self.main_container, bg=BG_COLOR)
        self.content_viewport.place(relx=0.5, rely=0.5, anchor="center")
        self._update_content_viewport()

        # ── Login Screen (shown initially) ───────────────────────────────
        self.login_screen = LoginScreen(self.content_viewport, self._on_login_success)
        self.login_screen.place(in_=self.content_viewport, x=0, y=0, relwidth=1, relheight=1)

        # ── App Content (hidden until login) ─────────────────────────────
        self.app_content = tk.Frame(self.content_viewport, bg=BG_COLOR)
        # Not packed yet - will be shown after login

        self._build_app_content()

    def _on_main_container_resize(self, event=None):
        self._update_content_viewport()

    def _update_content_viewport(self):
        """Keep app content centered while adapting to the current screen shape."""
        available_w = max(1, self.main_container.winfo_width())
        available_h = max(1, self.main_container.winfo_height())
        viewport_w = min(DEVICE_WIDTH, available_w)
        viewport_h = min(DEVICE_HEIGHT, available_h)
        self.content_viewport.place_configure(width=viewport_w, height=viewport_h)

    def _build_app_content(self):
        """Build the main application content (shown after login)."""
        # ── Tab Navigation ───────────────────────────────────────────────
        tab_bar = tk.Frame(self.app_content, bg=TAB_DARK, height=40)
        tab_bar.pack(fill="x")
        tab_bar.pack_propagate(False)

        self.entry_tab_btn = tk.Button(
            tab_bar, text="Meter Entry", font=(FONT_FAMILY, 11, "bold"),
            bg=TAB_DARK, fg=WHITE, relief="flat", bd=0, cursor="hand2",
            activebackground=TAB_DARK, activeforeground=WHITE,
            command=lambda: self._switch_page("meter_entry"))
        self.entry_tab_btn.pack(side="left", fill="both", expand=True)

        self.progress_tab_btn = tk.Button(
            tab_bar, text="Progress", font=(FONT_FAMILY, 11, "bold"),
            bg=TAB_BLUE, fg=WHITE, relief="flat", bd=0, cursor="hand2",
            activebackground=TAB_BLUE, activeforeground=WHITE,
            command=lambda: self._switch_page("progress"))
        self.progress_tab_btn.pack(side="left", fill="both", expand=True)

        # ── Pages Container ─────────────────────────────────────────────
        self.pages_container = tk.Frame(self.app_content, bg=BG_COLOR)
        self.pages_container.pack(fill="both", expand=True)

        self._build_meter_entry_page()
        self._build_progress_page()
        self._switch_page("meter_entry")

    def _on_login_success(self, user: dict):
        """Handle successful login."""
        self._current_user = user

        # Store user info for profile menu

        # Switch to app content
        self.login_screen.place_forget()
        self.app_content.pack(fill="both", expand=True)

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
        
        logout_lbl = tk.Label(logout_frame, text="🚪 Logout", 
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
            self.login_screen.clear()
            self.app_content.pack_forget()
            self.login_screen.place(in_=self.main_container, x=0, y=0, relwidth=1, relheight=1)

    def _switch_page(self, page_name):
        self._current_page = page_name

        if page_name == "meter_entry":
            self.entry_tab_btn.config(bg=TAB_DARK, activebackground=TAB_DARK)
            self.progress_tab_btn.config(bg=TAB_BLUE, activebackground=TAB_BLUE)
            self.meter_entry_frame.tkraise()
        else:
            self.entry_tab_btn.config(bg=TAB_BLUE, activebackground=TAB_BLUE)
            self.progress_tab_btn.config(bg=TAB_DARK, activebackground=TAB_DARK)
            self.progress_frame.tkraise()
            self._animate_progress_bar()
            # Hide autocomplete when switching to progress tab
            self._hide_autocomplete()

    # ══════════════════════════════════════════════════════════════════════
    #  METER ENTRY PAGE (Non-Scrolling, Compact Grouped Card)
    # ══════════════════════════════════════════════════════════════════════
    def _build_meter_entry_page(self):
        self.meter_entry_frame = tk.Frame(self.pages_container, bg=BG_COLOR)
        self.meter_entry_frame.place(in_=self.pages_container, x=0, y=0, relwidth=1, relheight=1)

        # ── Fixed Header ─────────────────────────────────────────────────
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
        self._profile_btn = tk.Label(header_content, text="👤", font=(FONT_FAMILY, 14),
                                     bg=HEADER_BLUE, fg=WHITE, cursor="hand2")
        self._profile_btn.pack(side="right")
        self._profile_btn.bind("<Button-1>", lambda e, b=self._profile_btn: self._show_profile_menu(b))

        # ── Main Content Container (No Scrollbar) ────────────────────────
        main = tk.Frame(self.meter_entry_frame, bg=BG_COLOR)
        main.pack(fill="both", expand=True)

        px = 18

        # ── Search Section ───────────────────────────────────────────────
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
        self.search_input = RoundedEntry(search_section, placeholder="Type 001, 002...", height=42, radius=8, font=(FONT_FAMILY, 12), textvariable=self.search_var)
        self.search_input.pack(fill="x", pady=(2, 0))
        self.search_input.entry.bind("<Return>", self._on_search)
        self.search_input.entry.bind("<KeyRelease>", self._on_search_key)
        self.search_input.entry.bind("<FocusOut>", self._schedule_hide_autocomplete)

        # ── Grouped Detail Card ──────────────────────────────────────────
        self.group_card = GroupCard(main, radius=10, bg_color=WHITE)
        self.group_card.pack(fill="x", padx=px, pady=(2, 2))
        card = self.group_card.inner_frame

        # ── Consumer Details Section ─────────────────────────────────────
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

        # ── Present Reading Section ──────────────────────────────────────
        ri = tk.Frame(card, bg=WHITE)
        ri.pack(fill="x", pady=0)

        tk.Label(ri, text="Present Reading", font=(FONT_FAMILY, 12, "bold"), fg=DARK_TEXT, bg=WHITE).pack(anchor="w", pady=(0, 2))

        vcmd = (self.register(self._validate_numeric), "%P")

        self.present_var = tk.StringVar()
        self.reading_input = RoundedEntry(
            ri, placeholder="Enter current reading...",
            height=46, radius=8, bg=WHITE,
            font=(FONT_FAMILY, 15, "bold"), justify="left",
            textvariable=self.present_var)
        self.reading_input.pack(fill="x", pady=0)
        self.reading_input.set_validate(vcmd)

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

        # ── Exception Section ────────────────────────────────────────────
        ei = tk.Frame(card, bg=WHITE)
        ei.pack(fill="x", pady=0)

        tk.Label(ei, text="Exception", font=(FONT_FAMILY, 11, "bold"), fg=DARK_TEXT, bg=WHITE).pack(anchor="w", pady=(0, 2))

        self.exception_var = tk.StringVar(value="None")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Figma.TCombobox",
                         fieldbackground=INPUT_BG,
                         background=WHITE,
                         foreground=DARK_TEXT,
                         bordercolor=INPUT_BORDER,
                         arrowcolor=MID_TEXT,
                         relief="flat",
                         padding=6)
        style.map("Figma.TCombobox",
                   fieldbackground=[("readonly", INPUT_BG)],
                   bordercolor=[("focus", INPUT_FOCUS)])

        ttk.Combobox(ei, textvariable=self.exception_var,
                     values=["None", "Stuck Meter", "Leaking", "No Access", "Broken Seal"],
                     state="readonly", font=(FONT_FAMILY, 11, "bold"), style="Figma.TCombobox"
                     ).pack(fill="x", ipady=4, pady=(0, 2))

        # ── PRINT Button ─────────────────────────────────────────────────
        btn_wrapper = tk.Frame(main, bg=BG_COLOR)
        btn_wrapper.pack(fill="x", padx=px, pady=(0, 4))

        self.print_btn = tk.Button(
            btn_wrapper, text="🖨  PRINT",
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

        # ── Reprint Button ───────────────────────────────────────────────
        reprint_wrapper = tk.Frame(main, bg=BG_COLOR)
        reprint_wrapper.pack(fill="x", padx=px, pady=(0, 4))

        self.reprint_btn = tk.Button(
            reprint_wrapper, text="🔄  Reprint Last Receipt",
            font=(FONT_FAMILY, 11, "bold"),
            bg="#E3F2FD", fg=PRIMARY_BLUE,
            activebackground="#BBDEFB", activeforeground=PRIMARY_BLUE,
            relief="flat", bd=0, cursor="hand2",
            highlightthickness=0, command=self._show_reprint_dialog)
        self.reprint_btn.pack(fill="x", ipady=8)

        self.reprint_btn.bind("<Enter>", lambda e: e.widget.config(bg="#BBDEFB"))
        self.reprint_btn.bind("<Leave>", lambda e: e.widget.config(bg="#E3F2FD"))

        # ── Paper Status Controls (for demo/testing) ─────────────────────
        paper_control = tk.Frame(main, bg=BG_COLOR)
        paper_control.pack(fill="x", padx=px, pady=(4, 0))

        tk.Label(paper_control, text="Paper Status (Test):", font=(FONT_FAMILY, 9),
                 bg=BG_COLOR, fg=MID_TEXT).pack(side="left")

        paper_states = [
            ("OK", "ok", PAPER_OK),
            ("Low", "low", PAPER_LOW),
            ("Out", "out", PAPER_OUT),
            ("Jam", "jam", PAPER_JAM),
        ]

        for label, state, color in paper_states:
            btn = tk.Label(paper_control, text=label, font=(FONT_FAMILY, 8, "bold"),
                          bg=BG_COLOR, fg=color, cursor="hand2", padx=4)
            btn.pack(side="right")
            btn.bind("<Button-1>", lambda e, s=state: self.status_bar.set_paper_status(s))

        # ── Battery/Signal Controls (for demo/testing) ───────────────────
        signal_control = tk.Frame(main, bg=BG_COLOR)
        signal_control.pack(fill="x", padx=px, pady=(2, 0))

        tk.Label(signal_control, text="Signal:", font=(FONT_FAMILY, 9),
                 bg=BG_COLOR, fg=MID_TEXT).pack(side="left")
        for i in range(5):
            btn = tk.Label(signal_control, text=str(i), font=(FONT_FAMILY, 8),
                          bg=BG_COLOR, fg=PRIMARY_BLUE, cursor="hand2", padx=2)
            btn.pack(side="left")
            btn.bind("<Button-1>", lambda e, s=i: self.status_bar.set_signal(s))

        tk.Label(signal_control, text="| Battery:", font=(FONT_FAMILY, 9),
                 bg=BG_COLOR, fg=MID_TEXT).pack(side="left", padx=(10, 0))
        for level, label in [(100, "100"), (50, "50"), (20, "20"), (10, "10")]:
            btn = tk.Label(signal_control, text=label, font=(FONT_FAMILY, 8),
                          bg=BG_COLOR, fg=PRIMARY_BLUE, cursor="hand2", padx=2)
            btn.pack(side="left")
            btn.bind("<Button-1>", lambda e, l=level: self.status_bar.set_battery(l))


    # ══════════════════════════════════════════════════════════════════════
    #  PROGRESS PAGE (Non-Scrolling, Compact & Large Texts)
    # ══════════════════════════════════════════════════════════════════════
    def _build_progress_page(self):
        self.progress_frame = tk.Frame(self.pages_container, bg=BG_COLOR)
        self.progress_frame.place(in_=self.pages_container, x=0, y=0, relwidth=1, relheight=1)

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
        self._profile_btn2 = tk.Label(header_content, text="👤", font=(FONT_FAMILY, 14),
                                      bg=HEADER_BLUE, fg=WHITE, cursor="hand2")
        self._profile_btn2.pack(side="right")
        self._profile_btn2.bind("<Button-1>", lambda e, b=self._profile_btn2: self._show_profile_menu(b))

        # ── Main Content Container (wrapped in _progress_content for showing/hiding) ────────────────────────
        self._progress_content = tk.Frame(self.progress_frame, bg=BG_COLOR)
        self._progress_content.pack(fill="both", expand=True)
        
        main = tk.Frame(self._progress_content, bg=BG_COLOR)
        main.pack(fill="both", expand=True)

        px = 18

        # ── Assigned Zone Section ────────────────────────────────────────
        zi = tk.Frame(main, bg=BG_COLOR)
        zi.pack(fill="x", padx=px, pady=(12, 6))

        tk.Label(zi, text="Assigned Zone", font=(FONT_FAMILY, 11, "bold"), fg=DARK_TEXT, bg=BG_COLOR).pack(anchor="w", pady=(0, 4))

        self._zone_combo = ttk.Combobox(zi, textvariable=self._current_zone,
                                   values=get_all_zone_names(),
                                   state="readonly", font=(FONT_FAMILY, 12, "bold"),
                                   style="Figma.TCombobox")
        self._zone_combo.pack(fill="x", ipady=4)
        self._zone_combo.bind("<<ComboboxSelected>>", self._on_zone_change)

        # ── Today's Progress Card (Blue) ─────────────────────────────────
        self._progress_canvas = tk.Canvas(main, bg=BG_COLOR, highlightthickness=0, height=280)
        self._progress_canvas.pack(fill="x", padx=px, pady=(6, 4))

        # ── Zone Info Card (White) ───────────────────────────────────────
        self._zone_info_canvas = tk.Canvas(main, bg=BG_COLOR, highlightthickness=0, height=130)
        self._zone_info_canvas.pack(fill="x", padx=px, pady=(4, 16))

        self._zone_info_canvas.bind("<Configure>", self._redraw_zone_card)
        self._progress_canvas.bind("<Configure>", self._redraw_progress_card)

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
        sync_txt = c.create_text(w - 38, 30, text="⟲", font=(FONT_FAMILY, 30, "bold"), fill=PRIMARY_BLUE, anchor="center", tags="sync_btn")
        
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
        c.create_text(cx, h - 15, text="Tap for details →", font=(FONT_FAMILY, 9), fill="#B3D4FC")
        
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
        back_btn = tk.Label(header, text="← Back", font=(FONT_FAMILY, 12, "bold"),
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
            status_text = "✓" if is_read else "○"
            status_color = SUCCESS_GREEN if is_read else MID_TEXT
            status_lbl = tk.Label(row_frame, text=status_text, font=(FONT_FAMILY, 8, "bold"),
                    bg=bg_color, fg=status_color, width=6, anchor="center")
            status_lbl.pack(side="left", padx=3, pady=6)
            # Tooltip effect on hover
            status_lbl.bind("<Enter>", lambda e, lbl=status_lbl, txt=status_text: lbl.config(text="✓ Read" if txt == "✓" else "○ Pending"))
            status_lbl.bind("<Leave>", lambda e, lbl=status_lbl, txt=status_text: lbl.config(text=txt))
            
            # Reading (width 8, centered to align with header)
            reading_val = str(consumer['reading_value']) if is_read and consumer['reading_value'] else "-"
            tk.Label(row_frame, text=reading_val, font=(FONT_FAMILY, 10),
                    bg=bg_color, fg=DARK_TEXT, width=8, anchor="center").pack(side="left", padx=3, pady=6)
            
            # Reprint button for read items (width 10, centered)
            if is_read:
                reprint_btn = tk.Label(row_frame, text="🖨 Print", font=(FONT_FAMILY, 10, "bold"),
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
        self._spawn_overlay("Syncing...", "Refreshing from database", self._do_sync)

    def _do_sync(self):
        time.sleep(0.8)
        self.after(0, self._finish_sync)

    def _finish_sync(self):
        self._dismiss_overlay()
        self._refresh_zone_stats()
        messagebox.showinfo("Sync Complete", "Zone data refreshed from the database.")

    def _refresh_zone_stats(self):
        """Reload zone statistics from the database and redraw the progress tab."""
        self._zones_data = get_zone_stats()
        self._redraw_zone_card()
        self._animate_progress_bar()

    # ── Search & Load Consumer ───────────────────────────────────────────
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
        results = search_consumers_by_zone(query, zone)
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
        
        consumer = search_consumer(meter_no)
        if consumer is None:
            # Also try zone-filtered partial search
            zone = self._current_zone.get()
            results = search_consumers_by_zone(meter_no, zone)
            if results:
                consumer = results[0]
            else:
                messagebox.showwarning("Not Found", f"No consumer found for '{meter_no}' in {zone}.")
                self._current_consumer = None
                self._clear_consumer_details()
                return
        self._load_consumer(consumer)

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

    # ══════════════════════════════════════════════════════════════════════
    #  VALIDATION & OVERLAYS
    # ══════════════════════════════════════════════════════════════════════
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
            self._set_consumption_state("invalid", "No Consumer", "Search a meter first", "⚠ No consumer loaded")
            return
        try:
            present = int(reading_str)
        except ValueError:
            self._set_consumption_state("invalid", "Invalid Input", "Must be a number", "⚠ Invalid entry")
            return
        previous = self._current_consumer["previous_reading"]
        consumption = present - previous
        if consumption < 0:
            self._set_consumption_state("invalid", "INVALID READING", "Reading cannot be less than previous", f"⚠ Reading must be ≥ previous ({previous})")
            self._shake_widget(self.reading_input)
        elif consumption > HIGH_CONSUMPTION_THRESHOLD:
            self._set_consumption_state("warning", str(consumption), "Unusually high – please verify", "⚠ High consumption detected")
        else:
            self._set_consumption_state("valid", str(consumption), "Valid reading", "")

    def _set_consumption_state(self, state, title, message, validation_msg):
        # Store the state for print validation
        self._consumption_state = state
        
        if state == "valid":
            title_color = VALID_TEXT
            msg_color = VALID_TEXT
            self.reading_input.set_border_color(VALID_BORDER)
            self._validation_icon_label.config(text="✓ " + validation_msg if validation_msg else "", fg=VALID_TEXT)
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
        self.after(0, self._proceed_to_printing)

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
        sc.create_text(cx, cy-55, text="✓", font=(FONT_FAMILY, 24, "bold"), fill=WHITE)
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

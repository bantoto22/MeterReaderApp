"""Water Meter Reader launcher.

Default mode: tkinter UI
Qt hybrid mode: `python main.py --qt`
"""

from __future__ import annotations

import sys

from src.meter_reader import MeterReaderApp


def run_tk() -> None:
    app = MeterReaderApp()
    app.mainloop()


def run_qt() -> int:
    from src.qt_hybrid_app import run_qt_hybrid

    return run_qt_hybrid()


if __name__ == "__main__":
    if "--qt" in sys.argv:
        raise SystemExit(run_qt())
    run_tk()

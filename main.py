"""Water Meter Reader launcher."""

from __future__ import annotations

import sys


if __name__ == "__main__":
    try:
        from src.qt_hybrid_app import run_qt_hybrid
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(run_qt_hybrid())

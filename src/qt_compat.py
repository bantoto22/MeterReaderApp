"""Qt compatibility layer for PySide6 and PyQt6."""

from __future__ import annotations

import importlib.util
import os
import platform
from pathlib import Path

QT_BINDING = ""
QT_BINDING_VERSION = ""
QT_VERSION = ""


def _raise_missing_binding() -> None:
    raise RuntimeError(
        "No supported Qt binding was found.\n\n"
        "Install one of the following:\n\n"
        "PySide6:\n"
        "    python3 -m pip install PySide6\n\n"
        "PyQt6 on Raspberry Pi OS:\n"
        "    sudo apt install python3-pyqt6 python3-pyqt6.qtqml python3-pyqt6.qtquick"
    )


try:
    if os.name == "nt":
        pyside_spec = importlib.util.find_spec("PySide6")
        if pyside_spec and pyside_spec.origin:
            os.add_dll_directory(str(Path(pyside_spec.origin).resolve().parent))

    from PySide6 import __version__ as PYSIDE_VERSION
    from PySide6.QtCore import QObject, Property, Qt, QTimer, QUrl, Signal, Slot, qVersion
    from PySide6.QtGui import QFont
    from PySide6.QtQuickWidgets import QQuickWidget
    from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

    QT_BINDING = "PySide6"
    QT_BINDING_VERSION = PYSIDE_VERSION
    QT_VERSION = qVersion()
except ImportError:
    try:
        from PyQt6.QtCore import (
            QObject,
            Qt,
            QTimer,
            QUrl,
            QT_VERSION_STR,
            PYQT_VERSION_STR,
            pyqtProperty as Property,
            pyqtSignal as Signal,
            pyqtSlot as Slot,
        )
        from PyQt6.QtGui import QFont
        from PyQt6.QtQuickWidgets import QQuickWidget
        from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

        QT_BINDING = "PyQt6"
        QT_BINDING_VERSION = PYQT_VERSION_STR
        QT_VERSION = QT_VERSION_STR
    except ImportError:
        _raise_missing_binding()


PYTHON_VERSION = platform.python_version()
CPU_ARCH = platform.machine() or "unknown"

__all__ = [
    "QApplication",
    "QFont",
    "QMainWindow",
    "QObject",
    "Property",
    "QQuickWidget",
    "QStackedWidget",
    "QT_BINDING",
    "QT_BINDING_VERSION",
    "QT_VERSION",
    "CPU_ARCH",
    "PYTHON_VERSION",
    "QTimer",
    "Qt",
    "QUrl",
    "QVBoxLayout",
    "QWidget",
    "Signal",
    "Slot",
]

"""Qt Widgets + QML hybrid UI for the Water Meter Reader app."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Property, Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from .database import (
        authenticate_user,
        get_all_zone_names,
        get_zone_stats,
        init_db,
        save_reading,
        search_consumer,
        search_consumers_by_zone,
    )
except ImportError:
    from database import (
        authenticate_user,
        get_all_zone_names,
        get_zone_stats,
        init_db,
        save_reading,
        search_consumer,
        search_consumers_by_zone,
    )


class ZoneOverviewBridge(QObject):
    zoneSummaryChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._zone_summary = ""

    @Property(str, notify=zoneSummaryChanged)
    def zoneSummary(self) -> str:
        return self._zone_summary

    @Slot()
    def refresh(self) -> None:
        stats = get_zone_stats()
        if not stats:
            self._zone_summary = "No zone data"
        else:
            lines = []
            for zone_name in sorted(stats.keys()):
                zone = stats[zone_name]
                lines.append(
                    f"{zone_name}: {zone['read']}/{zone['households']} read | flagged: {zone['flagged']}"
                )
            self._zone_summary = "\n".join(lines)
        self.zoneSummaryChanged.emit()


class LoginPage(QWidget):
    loginSuccess = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        title = QLabel("Water Meter Reader")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        subtitle = QLabel("Sign in to start field readings")
        subtitle.setStyleSheet("color: #4d5b6a;")

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Password")

        login_btn = QPushButton("Login")
        login_btn.clicked.connect(self._attempt_login)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(self.username_input)
        layout.addWidget(self.password_input)
        layout.addWidget(login_btn)
        layout.addStretch(1)

    def _attempt_login(self) -> None:
        user = authenticate_user(self.username_input.text().strip(), self.password_input.text().strip())
        if not user:
            QMessageBox.warning(self, "Login failed", "Invalid username or password.")
            return
        self.loginSuccess.emit(user)


class MeterEntryPage(QWidget):
    requestOverview = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._consumer = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)

        top_row = QHBoxLayout()
        self.user_label = QLabel("Reader: -")
        overview_btn = QPushButton("Zone Overview")
        overview_btn.clicked.connect(self.requestOverview.emit)
        top_row.addWidget(self.user_label)
        top_row.addStretch(1)
        top_row.addWidget(overview_btn)

        form = QFormLayout()
        self.zone_select = QComboBox()
        self.zone_select.addItems(get_all_zone_names())
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Meter No (e.g., MTR-001)")
        self.present_input = QLineEdit()
        self.present_input.setPlaceholderText("Present reading")

        self.result_label = QLabel("Search a consumer to begin.")
        self.result_label.setWordWrap(True)

        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._search_consumer)
        save_btn = QPushButton("Save Reading")
        save_btn.clicked.connect(self._save_reading)

        form.addRow("Zone", self.zone_select)
        form.addRow("Meter", self.search_input)
        form.addRow("Present", self.present_input)

        root.addLayout(top_row)
        root.addSpacing(8)
        root.addLayout(form)
        root.addWidget(search_btn)
        root.addWidget(save_btn)
        root.addWidget(self.result_label)
        root.addStretch(1)

    def set_user(self, user: dict) -> None:
        self.user_label.setText(f"Reader: {user['name']} ({user['id']})")

    def _search_consumer(self) -> None:
        query = self.search_input.text().strip()
        if query.isdigit():
            query = f"MTR-{query.zfill(3)}"

        consumer = search_consumer(query, unread_only=False)
        if consumer is None:
            matches = search_consumers_by_zone(query, self.zone_select.currentText(), limit=1, unread_only=False)
            consumer = matches[0] if matches else None

        if consumer is None:
            self._consumer = None
            self.result_label.setText("Consumer not found in selected zone.")
            return

        self._consumer = consumer
        self.result_label.setText(
            f"{consumer['name']} | {consumer['meter_no']} | prev: {consumer['previous_reading']}"
        )

    def _save_reading(self) -> None:
        if not self._consumer:
            QMessageBox.warning(self, "No consumer", "Search a consumer before saving.")
            return

        try:
            present = int(self.present_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid reading", "Present reading must be numeric.")
            return

        previous = int(self._consumer["previous_reading"])
        if present < previous:
            QMessageBox.warning(self, "Invalid reading", "Present reading cannot be lower than previous.")
            return

        consumption = present - previous
        save_reading(self._consumer["id"], present, consumption)
        self._consumer["previous_reading"] = present
        self.result_label.setText(
            f"Saved. {self._consumer['name']} | consumption: {consumption}"
        )
        self.present_input.clear()


class ZoneOverviewPage(QWidget):
    backRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.bridge = ZoneOverviewBridge()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        quick = QQuickWidget()
        quick.rootContext().setContextProperty("zoneBridge", self.bridge)
        qml_path = Path(__file__).resolve().parent.parent / "assets" / "qml" / "ZoneOverview.qml"
        quick.setSource(str(qml_path))
        quick.setResizeMode(QQuickWidget.SizeRootObjectToView)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 8, 16, 12)
        back_btn = QPushButton("Back to Meter Entry")
        back_btn.clicked.connect(self.backRequested.emit)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.bridge.refresh)
        footer_layout.addWidget(back_btn)
        footer_layout.addStretch(1)
        footer_layout.addWidget(refresh_btn)

        layout.addWidget(quick, 1)
        layout.addWidget(footer)

        self.bridge.refresh()


class HybridMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Water Meter Reader - Qt Hybrid")
        self.resize(920, 620)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.login_page = LoginPage()
        self.meter_page = MeterEntryPage()
        self.overview_page = ZoneOverviewPage()

        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.meter_page)
        self.stack.addWidget(self.overview_page)

        self.login_page.loginSuccess.connect(self._on_login_success)
        self.meter_page.requestOverview.connect(self._open_overview)
        self.overview_page.backRequested.connect(self._open_meter_entry)

    def _on_login_success(self, user: dict) -> None:
        self.meter_page.set_user(user)
        self.stack.setCurrentWidget(self.meter_page)

    def _open_overview(self) -> None:
        self.overview_page.bridge.refresh()
        self.stack.setCurrentWidget(self.overview_page)

    def _open_meter_entry(self) -> None:
        self.stack.setCurrentWidget(self.meter_page)


def run_qt_hybrid() -> int:
    init_db()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Montserrat", 10))
    app.setStyle("Fusion")
    win = HybridMainWindow()
    win.show()
    return app.exec()

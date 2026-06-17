"""Qt Widgets + QML hybrid UI for the Water Meter Reader app."""

from __future__ import annotations

import sys
import os
import importlib.util
from datetime import datetime
from pathlib import Path

os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"

if os.name == "nt":
    pyside_spec = importlib.util.find_spec("PySide6")
    if pyside_spec and pyside_spec.origin:
        os.add_dll_directory(str(Path(pyside_spec.origin).resolve().parent))

from PySide6.QtCore import QObject, Property, Qt, Signal, Slot, QUrl
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from .database import (
        authenticate_user,
        get_all_zone_names,
        get_zone_consumers_with_status,
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
        get_zone_consumers_with_status,
        get_zone_stats,
        init_db,
        save_reading,
        search_consumer,
        search_consumers_by_zone,
    )


class LoginBridge(QObject):
    loginSuccess = Signal(dict)
    loginFailed = Signal()
    errorMessageChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._error_message = ""

    @Property(str, notify=errorMessageChanged)
    def errorMessage(self) -> str:
        return self._error_message

    @Slot(str, str)
    def attemptLogin(self, username, password):
        username = username.strip()
        password = password.strip()
        if not username or not password:
            self._error_message = "Please enter username and password"
            self.errorMessageChanged.emit()
            self.loginFailed.emit()
            return

        user = authenticate_user(username, password)
        if not user:
            self._error_message = "Invalid username or password."
            self.errorMessageChanged.emit()
            self.loginFailed.emit()
            return

        self._error_message = ""
        self.errorMessageChanged.emit()
        self.loginSuccess.emit(user)


class AppBridge(QObject):
    # Tab property
    currentTabChanged = Signal()
    readerNameChanged = Signal()
    readerIdChanged = Signal()
    statusTimeChanged = Signal()
    batteryLevelChanged = Signal()
    paperStatusChanged = Signal()
    searchSuggestionsChanged = Signal()
    zoneConsumersChanged = Signal()
    progressDetailsVisibleChanged = Signal()
    logoutRequested = Signal()
    welcomeToastRequested = Signal(str)
    operationBusyChanged = Signal()
    operationBusyMessageChanged = Signal()
    
    # Meter Entry properties
    zonesChanged = Signal()
    selectedZoneChanged = Signal()
    searchQueryChanged = Signal()
    searchUnreadOnlyChanged = Signal()
    
    # Consumer info properties
    accountNoChanged = Signal()
    consumerNameChanged = Signal()
    previousReadingChanged = Signal()
    presentReadingChanged = Signal()
    consumptionChanged = Signal()
    validationColorChanged = Signal()
    validationMessageChanged = Signal()
    
    # Exception properties
    exceptionsChanged = Signal()
    selectedExceptionChanged = Signal()

    # Sync properties
    syncStatusChanged = Signal()
    syncStatusColorChanged = Signal()
    syncPendingCountChanged = Signal()
    saveTargetChanged = Signal()
    backupStateChanged = Signal()
    lastSyncChanged = Signal()
    lastPullMirrorChanged = Signal()
    autoPullEnabledChanged = Signal()
    autoPushEnabledChanged = Signal()
    pullIntervalChanged = Signal()

    # Circular progress / dashboard stats
    overallPercentageChanged = Signal()
    overallFractionChanged = Signal()
    zoneReadFractionChanged = Signal()
    zoneCompletionPercentageChanged = Signal()
    zoneFlaggedCountChanged = Signal()
    zoneRemainingCountChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._current_tab = 0
        self._reader_name = "User"
        self._reader_id = ""

        self._status_time = datetime.now().strftime("%I:%M %p")
        self._battery_level = 85
        self._paper_status = "OK"
        self._search_suggestions = []
        self._zone_consumers = []
        self._progress_details_visible = False
        self._operation_busy = False
        self._operation_busy_message = ""
        
        self._zones = get_all_zone_names()
        self._selected_zone = self._zones[0] if self._zones else ""
        self._search_query = ""
        self._search_unread_only = True
        
        self._account_no = "-"
        self._consumer_name = "-"
        self._previous_reading = "-"
        self._present_reading = ""
        self._consumption = "-"
        self._validation_color = "#94a3b8"
        self._validation_message = "-"
        
        self._exceptions = ["None", "Stuck Meter", "Leaking", "No Access", "Broken Seal"]
        self._selected_exception = "None"

        self._sync_status = "Offline"
        self._sync_status_color = "#475569"
        self._sync_pending_count = 0
        self._save_target = "Local SQLite only"
        self._backup_state = "Not configured"
        self._last_sync = "Never"
        self._last_pull_mirror = 0
        self._auto_pull_enabled = True
        self._auto_push_enabled = True
        self._pull_interval = 60

        self._overall_percentage = 0
        self._overall_fraction = "0/0"
        self._zone_read_fraction = "0/0"
        self._zone_completion_percentage = 0
        self._zone_flagged_count = 0
        self._zone_remaining_count = 0

        self._consumer = None
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(60_000)
        self._clock_timer.timeout.connect(self._tick_status_clock)
        self._clock_timer.start()

        self._refresh_search_suggestions()
        self._refresh_zone_consumers()
        self.update_stats()

    # Properties
    @Property(int, notify=zoneRemainingCountChanged)
    def zoneRemainingCount(self) -> int:
        return self._zone_remaining_count
    @Property(int, notify=currentTabChanged)
    def currentTab(self) -> int:
        return self._current_tab

    @currentTab.setter
    def currentTab(self, val: int) -> None:
        if self._current_tab != val:
            self._current_tab = val
            self.currentTabChanged.emit()

    @Property(str, notify=readerNameChanged)
    def readerName(self) -> str:
        return self._reader_name

    @Property(str, notify=readerIdChanged)
    def readerId(self) -> str:
        return self._reader_id

    @Property(str, notify=statusTimeChanged)
    def statusTime(self) -> str:
        return self._status_time

    @Property(int, notify=batteryLevelChanged)
    def batteryLevel(self) -> int:
        return self._battery_level

    @Property(str, notify=paperStatusChanged)
    def paperStatus(self) -> str:
        return self._paper_status

    @Property(list, notify=searchSuggestionsChanged)
    def searchSuggestions(self) -> list:
        return self._search_suggestions

    @Property(list, notify=zoneConsumersChanged)
    def zoneConsumers(self) -> list:
        return self._zone_consumers

    @Property(bool, notify=progressDetailsVisibleChanged)
    def progressDetailsVisible(self) -> bool:
        return self._progress_details_visible

    @Property(bool, notify=operationBusyChanged)
    def operationBusy(self) -> bool:
        return self._operation_busy

    @Property(str, notify=operationBusyMessageChanged)
    def operationBusyMessage(self) -> str:
        return self._operation_busy_message

    def set_user(self, user: dict) -> None:
        self._reader_name = user.get('name', 'User')
        self._reader_id = user.get('id', '')
        self.readerNameChanged.emit()
        self.readerIdChanged.emit()

    @Slot()
    def showWelcomeToast(self) -> None:
        self.welcomeToastRequested.emit(f"Welcome, {self._reader_name}!")

    def _set_operation_busy(self, busy: bool, message: str = "") -> None:
        if self._operation_busy != busy:
            self._operation_busy = busy
            self.operationBusyChanged.emit()
        if self._operation_busy_message != message:
            self._operation_busy_message = message
            self.operationBusyMessageChanged.emit()

    def clear_user(self) -> None:
        self._reader_name = "User"
        self._reader_id = ""
        self.readerNameChanged.emit()
        self.readerIdChanged.emit()

    def _tick_status_clock(self) -> None:
        self._status_time = datetime.now().strftime("%I:%M %p")
        self.statusTimeChanged.emit()

    def _refresh_search_suggestions(self) -> None:
        query = self._search_query.strip()
        if not query:
            self._search_suggestions = []
            self.searchSuggestionsChanged.emit()
            return

        try:
            self._search_suggestions = search_consumers_by_zone(
                query,
                self._selected_zone,
                limit=6,
                unread_only=self._search_unread_only,
            )
        except Exception:
            self._search_suggestions = []
        self.searchSuggestionsChanged.emit()

    def _refresh_zone_consumers(self) -> None:
        if not self._selected_zone:
            self._zone_consumers = []
            self.zoneConsumersChanged.emit()
            return

        try:
            self._zone_consumers = get_zone_consumers_with_status(self._selected_zone)
        except Exception:
            self._zone_consumers = []
        self.zoneConsumersChanged.emit()

    @Property(list, notify=zonesChanged)
    def zones(self) -> list:
        return self._zones

    @Property(str, notify=selectedZoneChanged)
    def selectedZone(self) -> str:
        return self._selected_zone

    @selectedZone.setter
    def selectedZone(self, val: str) -> None:
        if self._selected_zone != val:
            self._selected_zone = val
            self.selectedZoneChanged.emit()
            self.update_stats()
            self._refresh_search_suggestions()
            if self._progress_details_visible:
                self._refresh_zone_consumers()

    @Property(str, notify=searchQueryChanged)
    def searchQuery(self) -> str:
        return self._search_query

    @searchQuery.setter
    def searchQuery(self, val: str) -> None:
        if self._search_query != val:
            self._search_query = val
            self.searchQueryChanged.emit()
            self._refresh_search_suggestions()

    @Property(bool, notify=searchUnreadOnlyChanged)
    def searchUnreadOnly(self) -> bool:
        return self._search_unread_only

    @searchUnreadOnly.setter
    def searchUnreadOnly(self, val: bool) -> None:
        if self._search_unread_only != val:
            self._search_unread_only = val
            self.searchUnreadOnlyChanged.emit()

    # Consumer Details properties
    @Property(str, notify=accountNoChanged)
    def accountNo(self) -> str:
        return self._account_no

    @Property(str, notify=consumerNameChanged)
    def consumerName(self) -> str:
        return self._consumer_name

    @Property(str, notify=previousReadingChanged)
    def previousReading(self) -> str:
        return self._previous_reading

    @Property(str, notify=presentReadingChanged)
    def presentReading(self) -> str:
        return self._present_reading

    @presentReading.setter
    def presentReading(self, val: str) -> None:
        if self._present_reading != val:
            self._present_reading = val
            self.presentReadingChanged.emit()
            self.calculate_consumption()

    @Property(str, notify=consumptionChanged)
    def consumption(self) -> str:
        return self._consumption

    @Property(str, notify=validationColorChanged)
    def validationColor(self) -> str:
        return self._validation_color

    @Property(str, notify=validationMessageChanged)
    def validationMessage(self) -> str:
        return self._validation_message

    # Exception properties
    @Property(list, notify=exceptionsChanged)
    def exceptions(self) -> list:
        return self._exceptions

    @Property(str, notify=selectedExceptionChanged)
    def selectedException(self) -> str:
        return self._selected_exception

    @selectedException.setter
    def selectedException(self, val: str) -> None:
        if self._selected_exception != val:
            self._selected_exception = val
            self.selectedExceptionChanged.emit()

    # Sync Settings properties
    @Property(str, notify=syncStatusChanged)
    def syncStatus(self) -> str:
        return self._sync_status

    @Property(str, notify=syncStatusColorChanged)
    def syncStatusColor(self) -> str:
        return self._sync_status_color

    @Property(int, notify=syncPendingCountChanged)
    def syncPendingCount(self) -> int:
        return self._sync_pending_count

    @Property(str, notify=saveTargetChanged)
    def saveTarget(self) -> str:
        return self._save_target

    @Property(str, notify=backupStateChanged)
    def backupState(self) -> str:
        return self._backup_state

    @Property(str, notify=lastSyncChanged)
    def lastSync(self) -> str:
        return self._last_sync

    @Property(int, notify=lastPullMirrorChanged)
    def lastPullMirror(self) -> int:
        return self._last_pull_mirror

    @Property(bool, notify=autoPullEnabledChanged)
    def autoPullEnabled(self) -> bool:
        return self._auto_pull_enabled

    @autoPullEnabled.setter
    def autoPullEnabled(self, val: bool) -> None:
        if self._auto_pull_enabled != val:
            self._auto_pull_enabled = val
            self.autoPullEnabledChanged.emit()

    @Property(bool, notify=autoPushEnabledChanged)
    def autoPushEnabled(self) -> bool:
        return self._auto_push_enabled

    @autoPushEnabled.setter
    def autoPushEnabled(self, val: bool) -> None:
        if self._auto_push_enabled != val:
            self._auto_push_enabled = val
            self.autoPushEnabledChanged.emit()

    @Property(int, notify=pullIntervalChanged)
    def pullInterval(self) -> int:
        return self._pull_interval

    @pullInterval.setter
    def pullInterval(self, val: int) -> None:
        if self._pull_interval != val:
            self._pull_interval = val
            self.pullIntervalChanged.emit()

    # Circular progress stats properties
    @Property(int, notify=overallPercentageChanged)
    def overallPercentage(self) -> int:
        return self._overall_percentage

    @Property(str, notify=overallFractionChanged)
    def overallFraction(self) -> str:
        return self._overall_fraction

    @Property(str, notify=zoneReadFractionChanged)
    def zoneReadFraction(self) -> str:
        return self._zone_read_fraction

    @Property(int, notify=zoneCompletionPercentageChanged)
    def zoneCompletionPercentage(self) -> int:
        return self._zone_completion_percentage

    @Property(int, notify=zoneFlaggedCountChanged)
    def zoneFlaggedCount(self) -> int:
        return self._zone_flagged_count

    # Actions / slots
    @Slot()
    def searchConsumer(self) -> None:
        query = self._search_query.strip()
        if not query:
            return

        if query.isdigit():
            query = f"MTR-{query.zfill(3)}"
            self._search_query = query
            self.searchQueryChanged.emit()

        consumer = search_consumer(query, unread_only=self._search_unread_only)
        if consumer is None:
            matches = search_consumers_by_zone(query, self._selected_zone, limit=1, unread_only=self._search_unread_only)
            consumer = matches[0] if matches else None

        if consumer is None:
            self._consumer = None
            self._account_no = "-"
            self._consumer_name = "Consumer not found"
            self._previous_reading = "-"
            self._present_reading = ""
            self._consumption = "-"
        else:
            self._consumer = consumer
            self._account_no = str(consumer["id"])
            self._consumer_name = consumer["name"]
            self._previous_reading = str(consumer["previous_reading"])
            self._present_reading = ""
            self._consumption = "-"

        self.accountNoChanged.emit()
        self.consumerNameChanged.emit()
        self.previousReadingChanged.emit()
        self.presentReadingChanged.emit()
        self.consumptionChanged.emit()

    @Slot(str)
    def selectSearchSuggestion(self, meter_no: str) -> None:
        self._search_query = meter_no
        self.searchQueryChanged.emit()
        self._refresh_search_suggestions()
        self.searchConsumer()

    @Slot()
    def openProgressDetails(self) -> None:
        self._progress_details_visible = True
        self.progressDetailsVisibleChanged.emit()
        self._refresh_zone_consumers()

    @Slot()
    def closeProgressDetails(self) -> None:
        self._progress_details_visible = False
        self.progressDetailsVisibleChanged.emit()

    @Slot(int)
    def reprintZoneConsumer(self, consumer_id: int) -> None:
        self._set_operation_busy(True, "Printing...")

        def finish_reprint() -> None:
            print(f"Reprint requested for consumer {consumer_id}")
            self._set_operation_busy(False, "")

        QTimer.singleShot(600, finish_reprint)

    @Slot()
    def logout(self) -> None:
        self.logoutRequested.emit()

    def calculate_consumption(self) -> None:
        if not self._consumer or not self._present_reading:
            self._consumption = "-"
            self._validation_color = "#94a3b8"
            self._validation_message = "-"
            self.consumptionChanged.emit()
            self.validationColorChanged.emit()
            self.validationMessageChanged.emit()
            return

        try:
            present = int(self._present_reading)
            previous = int(self._consumer["previous_reading"])
            diff = present - previous
            
            if diff < 0:
                self._consumption = str(diff)
                self._validation_color = "#EF4444"
                self._validation_message = "Invalid: Lower than previous"
            elif diff > 500:
                self._consumption = str(diff)
                self._validation_color = "#F59E0B"
                self._validation_message = "Warning: High Consumption"
            else:
                self._consumption = str(diff)
                self._validation_color = "#10B981"
                self._validation_message = "Valid"
        except Exception:
            self._consumption = "-"
            self._validation_color = "#EF4444"
            self._validation_message = "Numeric error"

        self.consumptionChanged.emit()
        self.validationColorChanged.emit()
        self.validationMessageChanged.emit()

    @Slot()
    def saveReading(self) -> None:
        self.printReceipt()

    @Slot()
    def printReceipt(self) -> None:
        if not self._consumer or not self._present_reading:
            return

        try:
            present = int(self._present_reading)
            previous = int(self._consumer["previous_reading"])
            if present < previous:
                return

            self._set_operation_busy(True, "Printing...")

            def finish_print() -> None:
                try:
                    consumption = present - previous
                    save_reading(self._consumer["id"], present, consumption)

                    self._consumer["previous_reading"] = present
                    self._previous_reading = str(present)
                    self._present_reading = ""
                    self._consumption = "-"
                    self._validation_color = "#10B981"
                    self._validation_message = "Saved successfully!"

                    self.previousReadingChanged.emit()
                    self.presentReadingChanged.emit()
                    self.consumptionChanged.emit()
                    self.validationColorChanged.emit()
                    self.validationMessageChanged.emit()

                    self.update_stats()
                    if self._progress_details_visible:
                        self._refresh_zone_consumers()
                except Exception as e:
                    print(f"Error saving: {e}")
                finally:
                    self._set_operation_busy(False, "")

            QTimer.singleShot(600, finish_print)
        except Exception as e:
            print(f"Error saving: {e}")
            self._set_operation_busy(False, "")

    @Slot(int)
    def setBatteryLevel(self, level: int) -> None:
        self._battery_level = max(0, min(100, level))
        self.batteryLevelChanged.emit()

    @Slot(str)
    def setPaperStatus(self, status: str) -> None:
        normalized = (status or "OK").strip() or "OK"
        self._paper_status = normalized
        self.paperStatusChanged.emit()

    @Slot()
    def reprintLastReceipt(self) -> None:
        pass

    @Slot()
    def syncNow(self) -> None:
        self._set_operation_busy(True, "Syncing...")

        def finish_sync() -> None:
            self._sync_status = "Online"
            self._sync_status_color = "#10B981"
            self.syncStatusChanged.emit()
            self.syncStatusColorChanged.emit()
            self._set_operation_busy(False, "")

        QTimer.singleShot(900, finish_sync)

    @Slot()
    def update_stats(self) -> None:
        stats = get_zone_stats()
        if not stats:
            return

        # Overall completion calculations
        total_read = 0
        total_households = 0
        flagged = 0
        for z_name, z_data in stats.items():
            total_read += z_data["read"]
            total_households += z_data["households"]
            flagged += z_data["flagged"]

        if total_households > 0:
            self._overall_percentage = int((total_read / total_households) * 100)
        else:
            self._overall_percentage = 0

        self._overall_fraction = f"{total_read}/{total_households} read"
        self.overallPercentageChanged.emit()
        self.overallFractionChanged.emit()

        # Active Zone calculations
        active_zone = stats.get(self._selected_zone)
        if active_zone:
            self._zone_read_fraction = f"{active_zone['read']}/{active_zone['households']}"
            if active_zone['households'] > 0:
                self._zone_completion_percentage = int((active_zone['read'] / active_zone['households']) * 100)
            else:
                self._zone_completion_percentage = 0
            self._zone_flagged_count = active_zone["flagged"]
            self._zone_remaining_count = max(0, active_zone['households'] - active_zone['read'])
        else:
            self._zone_read_fraction = "0/0"
            self._zone_completion_percentage = 0
            self._zone_flagged_count = 0
            self._zone_remaining_count = 0

        self.zoneReadFractionChanged.emit()
        self.zoneCompletionPercentageChanged.emit()
        self.zoneFlaggedCountChanged.emit()
        self.zoneRemainingCountChanged.emit()
        if self._progress_details_visible:
            self._refresh_zone_consumers()


class LoginPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.bridge = LoginBridge()
        self.bridge.setParent(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.quick = QQuickWidget()
        self.quick.rootContext().setContextProperty("loginBridge", self.bridge)
        qml_path = Path(__file__).resolve().parent.parent / "assets" / "qml" / "Login.qml"
        self.quick.setSource(QUrl.fromLocalFile(str(qml_path)))
        self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        layout.addWidget(self.quick)


class MainContainerPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.bridge = AppBridge()
        self.bridge.setParent(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.quick = QQuickWidget()
        self.quick.rootContext().setContextProperty("appBridge", self.bridge)
        qml_path = Path(__file__).resolve().parent.parent / "assets" / "qml" / "MainContainer.qml"
        self.quick.setSource(QUrl.fromLocalFile(str(qml_path)))
        self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        layout.addWidget(self.quick)




class HybridMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Water Meter Reader - Qt Hybrid")
        self.resize(480, 750)  # Perfectly aligned with mobile handheld layout dimensions

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.login_page = LoginPage()
        self.main_page = MainContainerPage()

        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.main_page)

        self.login_page.bridge.loginSuccess.connect(self._on_login_success)
        self.main_page.bridge.logoutRequested.connect(self._on_logout_requested)

    def _on_login_success(self, user: dict) -> None:
        self.main_page.bridge.set_user(user)
        self.stack.setCurrentWidget(self.main_page)
        self.main_page.bridge.showWelcomeToast()

    def _on_logout_requested(self) -> None:
        self.main_page.bridge.clear_user()
        self.stack.setCurrentWidget(self.login_page)


def run_qt_hybrid() -> int:
    init_db()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Montserrat", 10))
    app.setStyle("Fusion")
    win = HybridMainWindow()
    win.show()
    return app.exec()



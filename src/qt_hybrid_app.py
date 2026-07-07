"""Qt Widgets + QML hybrid UI for the Water Meter Reader app."""

from __future__ import annotations

import sys
import os
import re
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"

try:
    from .qt_compat import (
        CPU_ARCH,
        QApplication,
        QFont,
        QMainWindow,
        QObject,
        Property,
        PYTHON_VERSION,
        QQuickWidget,
        QT_BINDING,
        QT_BINDING_VERSION,
        QT_VERSION,
        QStackedWidget,
        QTimer,
        Qt,
        QUrl,
        QVBoxLayout,
        QWidget,
        Signal,
        Slot,
    )
except ImportError:
    from qt_compat import (
        CPU_ARCH,
        QApplication,
        QFont,
        QMainWindow,
        QObject,
        Property,
        PYTHON_VERSION,
        QQuickWidget,
        QT_BINDING,
        QT_BINDING_VERSION,
        QT_VERSION,
        QStackedWidget,
        QTimer,
        Qt,
        QUrl,
        QVBoxLayout,
        QWidget,
        Signal,
        Slot,
    )

try:
    from .database import (
        authenticate_user,
        get_receipt_print_by_id,
        get_all_zone_names,
        get_latest_receipt_print,
        list_receipt_print_history,
        get_zone_consumers_with_status,
        get_zone_stats,
        init_db,
        save_receipt_print,
        replace_consumers_from_sync,
        save_reading,
        search_consumer,
        search_consumers_by_zone,
    )
except ImportError:
    from database import (
        authenticate_user,
        get_receipt_print_by_id,
        get_all_zone_names,
        get_latest_receipt_print,
        list_receipt_print_history,
        get_zone_consumers_with_status,
        get_zone_stats,
        init_db,
        save_receipt_print,
        replace_consumers_from_sync,
        save_reading,
        search_consumer,
        search_consumers_by_zone,
    )

try:
    from .handheld_sync import HandheldSyncDataAccess, SyncConfig
except ImportError:
    try:
        from handheld_sync import HandheldSyncDataAccess, SyncConfig
    except ImportError:
        HandheldSyncDataAccess = None
        SyncConfig = None

try:
    from .receipt import (
        build_receipt_text,
        build_reprint_receipt_text,
        can_use_system_printer,
        print_test_receipt,
        send_to_system_printer,
    )
except ImportError:
    from receipt import (
        build_receipt_text,
        build_reprint_receipt_text,
        can_use_system_printer,
        print_test_receipt,
        send_to_system_printer,
    )

QML_MAIN_FILE = Path(__file__).resolve().parent.parent / "assets" / "qml" / "MainContainer.qml"
QML_LOGIN_FILE = Path(__file__).resolve().parent.parent / "assets" / "qml" / "Login.qml"

print(f"Using Qt binding: {QT_BINDING}")
print(f"Python version: {PYTHON_VERSION}")
print(f"CPU architecture: {CPU_ARCH}")
print(f"Qt binding version: {QT_BINDING_VERSION}")
print(f"Qt version: {QT_VERSION}")
print(f"QML main file: {QML_MAIN_FILE}")


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
    alertRequested = Signal(str, str)
    receiptPreviewRequested = Signal(str, str)
    printPreviewRequested = Signal(str, str, str)
    printHistoryRequested = Signal()
    canReprintChanged = Signal()
    
    # Meter Entry properties
    zonesChanged = Signal()
    selectedZoneChanged = Signal()
    searchQueryChanged = Signal()

    
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
    syncLogsChanged = Signal()
    wifiStatusChanged = Signal()
    wifiStatusColorChanged = Signal()
    wifiNetworksChanged = Signal()
    wifiBusyChanged = Signal()
    testPrintBusyChanged = Signal()
    syncTaskFinished = Signal(object)
    wifiScanFinished = Signal(object, str)
    wifiConnectFinished = Signal(bool, str, str)
    wifiStatusResult = Signal(str, str)
    powerOffFailed = Signal(str)
    testPrintFinished = Signal(bool, str)
    printPreviewBusyChanged = Signal()
    printHistoryRecordsChanged = Signal()
    printHistoryDetailChanged = Signal()
    printExecutionFinished = Signal(object)

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
        self._last_receipt_entry = get_latest_receipt_print()
        self._last_receipt = self._last_receipt_entry["receipt_text"] if self._last_receipt_entry else None
        
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
        self._sync_logs = "No sync activity yet."
        self._sync_dal = None
        self._wifi_status = "Status: Checking..."
        self._wifi_status_color = "#526176"
        self._wifi_networks = []
        self._wifi_busy = False
        self._wifi_scan_silent = False
        self._test_print_busy = False
        self._print_preview_busy = False
        self._pending_print_job = None
        self._print_history_records = []
        self._print_history_detail = None

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

        self.syncTaskFinished.connect(self._finish_sync_task)
        self.wifiScanFinished.connect(self._finish_wifi_scan)
        self.wifiConnectFinished.connect(self._finish_wifi_connect)
        self.wifiStatusResult.connect(self._set_wifi_status)
        self.powerOffFailed.connect(self._finish_power_off_failure)
        self.testPrintFinished.connect(self._finish_test_print)
        self.printExecutionFinished.connect(self._finish_print_execution)

        self._wifi_timer = QTimer(self)
        self._wifi_timer.setInterval(5_000)
        self._wifi_timer.timeout.connect(self.refreshWifiStatus)
        self._wifi_timer.start()

        self._wifi_scan_timer = QTimer(self)
        self._wifi_scan_timer.setInterval(15_000)
        self._wifi_scan_timer.timeout.connect(self.refreshWifiNetworks)
        self._wifi_scan_timer.start()

        self._auto_pull_timer = QTimer(self)
        self._auto_pull_timer.timeout.connect(self._run_auto_pull)
        self._reset_auto_pull_timer()

        self._refresh_search_suggestions()
        self._refresh_zone_consumers()
        self.refreshPrintHistory()
        self.update_stats()
        self._init_sync()
        self.refreshWifiStatus()
        self.refreshWifiNetworks()

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

    @Property(bool, notify=canReprintChanged)
    def canReprint(self) -> bool:
        return self._last_receipt is not None

    def set_user(self, user: dict) -> None:
        self._reader_name = user.get('name', 'User')
        self._reader_id = user.get('id', '')
        self.readerNameChanged.emit()
        self.readerIdChanged.emit()
        self._last_receipt_entry = get_latest_receipt_print()
        self._last_receipt = self._last_receipt_entry["receipt_text"] if self._last_receipt_entry else None
        self.canReprintChanged.emit()

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

    @Property(list, notify=searchSuggestionsChanged)
    def searchSuggestions(self) -> list:
        return self._search_suggestions

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
            self._reset_auto_pull_timer()

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
        normalized = max(15, int(val or 60))
        if self._pull_interval != normalized:
            self._pull_interval = normalized
            self.pullIntervalChanged.emit()
            self._reset_auto_pull_timer()

    @Property(str, notify=syncLogsChanged)
    def syncLogs(self) -> str:
        return self._sync_logs

    @Property(str, notify=wifiStatusChanged)
    def wifiStatus(self) -> str:
        return self._wifi_status

    @Property(str, notify=wifiStatusColorChanged)
    def wifiStatusColor(self) -> str:
        return self._wifi_status_color

    @Property(list, notify=wifiNetworksChanged)
    def wifiNetworks(self) -> list:
        return self._wifi_networks

    @Property(bool, notify=wifiBusyChanged)
    def wifiBusy(self) -> bool:
        return self._wifi_busy

    @Property(bool, notify=testPrintBusyChanged)
    def testPrintBusy(self) -> bool:
        return self._test_print_busy

    @Property(bool, notify=printPreviewBusyChanged)
    def printPreviewBusy(self) -> bool:
        return self._print_preview_busy

    @Property(list, notify=printHistoryRecordsChanged)
    def printHistoryRecords(self) -> list:
        return self._print_history_records

    @Property(str, notify=printHistoryDetailChanged)
    def printHistoryDetailTitle(self) -> str:
        if not self._print_history_detail:
            return ""
        return f"Receipt #{self._print_history_detail.get('id', '')}"

    @Property(str, notify=printHistoryDetailChanged)
    def printHistoryDetailText(self) -> str:
        if not self._print_history_detail:
            return ""
        return str(self._print_history_detail.get("receipt_text") or "")

    @Property(bool, notify=printHistoryDetailChanged)
    def hasPrintHistoryDetail(self) -> bool:
        return self._print_history_detail is not None

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

    def _emit_sync_state(self) -> None:
        self.syncStatusChanged.emit()
        self.syncStatusColorChanged.emit()
        self.syncPendingCountChanged.emit()
        self.saveTargetChanged.emit()
        self.backupStateChanged.emit()
        self.lastSyncChanged.emit()
        self.lastPullMirrorChanged.emit()

    def _init_sync(self) -> None:
        if HandheldSyncDataAccess is None or SyncConfig is None:
            self._sync_status = "Sync Failed"
            self._sync_status_color = "#EF4444"
            self._sync_logs = "Sync module is unavailable."
            self.syncLogsChanged.emit()
            self._emit_sync_state()
            return
        try:
            cfg = SyncConfig.from_env(fail_fast=False)
            if not cfg.sync_enabled:
                self._sync_status = "Offline"
                self._sync_status_color = "#526176"
                self._sync_logs = "Handheld sync is disabled in the environment."
                self.syncLogsChanged.emit()
                self._emit_sync_state()
                return
            self._sync_dal = HandheldSyncDataAccess.from_env(fail_fast=True)
            self._sync_dal.start_sync_worker(interval_seconds=20)
            self._refresh_sync_snapshot()
        except Exception as exc:
            self._sync_dal = None
            self._sync_status = "Sync Failed"
            self._sync_status_color = "#EF4444"
            self._sync_logs = str(exc)
            self.syncLogsChanged.emit()
            self._emit_sync_state()

    def _refresh_sync_snapshot(self) -> None:
        if not self._sync_dal:
            self._emit_sync_state()
            return
        try:
            snapshot = self._sync_dal.get_sync_snapshot()
            self._sync_status = str(snapshot.get("status", "Offline"))
            self._sync_status_color = "#10B981" if self._sync_status == "Online" else "#526176"
            if snapshot.get("has_failed"):
                self._sync_status = "Sync Failed"
                self._sync_status_color = "#EF4444"
            self._sync_pending_count = int(snapshot.get("pending_count", 0))
            self._save_target = str(snapshot.get("save_target", "Local SQLite only"))
            self._backup_state = str(snapshot.get("backup_state", "Not configured"))
            self._last_sync = str(snapshot.get("last_sync_time") or "Never")
            entries = self._sync_dal.get_recent_audit_entries(limit=25)
            self._sync_logs = "\n\n".join(
                f"[{row.get('created_at', '')}] {str(row.get('status', '')).upper()}\n{row.get('message', '')}"
                for row in entries
            ) or "No sync activity yet."
            self.syncLogsChanged.emit()
        except Exception as exc:
            self._sync_status = "Sync Failed"
            self._sync_status_color = "#EF4444"
            self._sync_logs = str(exc)
            self.syncLogsChanged.emit()
        self._emit_sync_state()

    def _reset_auto_pull_timer(self) -> None:
        if not hasattr(self, "_auto_pull_timer"):
            return
        self._auto_pull_timer.stop()
        if self._auto_pull_enabled:
            self._auto_pull_timer.start(max(15, self._pull_interval) * 1000)

    def _run_auto_pull(self) -> None:
        if not self._auto_pull_enabled or not self._sync_dal or self._operation_busy:
            return

        def _task() -> None:
            try:
                consumers = self._sync_dal.loadAssignedConsumers(None)
                mirrored = replace_consumers_from_sync(consumers)
                self.syncTaskFinished.emit({"kind": "pull", "pulled": len(consumers), "mirrored": mirrored})
            except Exception as exc:
                self.syncTaskFinished.emit({"kind": "error", "error": str(exc), "silent": True})

        threading.Thread(target=_task, daemon=True).start()

    def _reload_current_consumer_from_db(self) -> None:
        if not self._consumer:
            return
        meter_no = (self._consumer.get("meter_no") or "").strip()
        if not meter_no:
            return
        refreshed = search_consumer(meter_no, unread_only=False)
        if refreshed is None:
            return
        self._consumer = refreshed
        self._account_no = str(refreshed.get("acct_no") or refreshed["id"])
        self._consumer_name = refreshed["name"]
        self._previous_reading = str(refreshed["previous_reading"])
        self.accountNoChanged.emit()
        self.consumerNameChanged.emit()
        self.previousReadingChanged.emit()

    def _finish_sync_task(self, result: dict) -> None:
        keep_busy = bool(result.get("keep_busy"))
        if not keep_busy:
            self._set_operation_busy(False, "")
        if result.get("kind") == "error":
            self._sync_status = "Sync Failed"
            self._sync_status_color = "#EF4444"
            self._sync_logs = str(result.get("error", "Sync failed"))
            self.syncLogsChanged.emit()
            self._emit_sync_state()
            if not result.get("silent"):
                self.alertRequested.emit("Sync Failed", self._sync_logs)
            return

        self._last_pull_mirror = int(result.get("mirrored", self._last_pull_mirror))
        self._zones = get_all_zone_names()
        self.zonesChanged.emit()
        self._refresh_search_suggestions()
        self._refresh_zone_consumers()
        self._reload_current_consumer_from_db()
        self.update_stats()
        self._refresh_sync_snapshot()
        if result.get("kind") == "sync" and not result.get("silent"):
            sync_result = result.get("result", {})
            self.alertRequested.emit(
                "Sync Complete",
                f"Synced: {sync_result.get('synced', 0)}\nFailed: {sync_result.get('failed', 0)}\nConflicts: {sync_result.get('conflicts', 0)}\nMirrored: {self._last_pull_mirror}",
            )

    def _save_to_sync_layer(self, consumer_id: int, present: int, consumption: int, exception: str, flagged: bool) -> None:
        if not self._sync_dal or not self._auto_push_enabled:
            return
        consumer = self._consumer or {}
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
            "is_flagged": bool(flagged),
            "reading_date": datetime.now().date().isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._sync_dal.saveMeterReading(payload)
        except Exception as exc:
            self._sync_logs = f"Sync save failed: {exc}"
            self.syncLogsChanged.emit()
        self._refresh_sync_snapshot()

    def _set_wifi_busy(self, busy: bool, status: str | None = None) -> None:
        self._wifi_busy = busy
        if status is not None:
            self._wifi_status = status
            self.wifiStatusChanged.emit()
        self.wifiBusyChanged.emit()

    def _set_wifi_status(self, status: str, color: str) -> None:
        self._wifi_status = status
        self._wifi_status_color = color
        self.wifiStatusChanged.emit()
        self.wifiStatusColorChanged.emit()

    def _start_wifi_scan(self, silent: bool = False) -> None:
        if self._wifi_busy:
            return
        self._wifi_scan_silent = silent
        self._set_wifi_busy(True, "Status: Scanning...")
        if not silent:
            self._wifi_status_color = "#2563EB"
            self.wifiStatusColorChanged.emit()

        def _task() -> None:
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
                self.wifiScanFinished.emit(networks, "")
            except FileNotFoundError:
                tool = "netsh" if os.name == "nt" else "nmcli"
                self.wifiScanFinished.emit([], f"Wi-Fi utility '{tool}' is not installed.")
            except subprocess.TimeoutExpired:
                self.wifiScanFinished.emit([], "Wi-Fi scan timed out. Please try again.")
            except Exception as exc:
                self.wifiScanFinished.emit([], str(exc))

        threading.Thread(target=_task, daemon=True).start()

    @Slot()
    def scanWifiNetworks(self) -> None:
        self._start_wifi_scan(False)

    @Slot()
    def refreshWifiNetworks(self) -> None:
        self._start_wifi_scan(True)

    def _finish_wifi_scan(self, networks: list, error: str) -> None:
        self._set_wifi_busy(False)
        silent = self._wifi_scan_silent
        self._wifi_scan_silent = False
        if error:
            self._wifi_networks = []
            self.wifiNetworksChanged.emit()
            if not silent:
                self._set_wifi_status(f"Status: Error - {error}", "#EF4444")
                self.alertRequested.emit("Wi-Fi Scan Failed", error)
            return
        self._wifi_networks = list(networks)
        self.wifiNetworksChanged.emit()
        if silent:
            return
        if networks:
            self._set_wifi_status(f"Status: Scan Complete ({len(networks)} found)", "#10B981")
        else:
            self._set_wifi_status("Status: No networks found", "#F59E0B")

    @Slot(str, str)
    def connectWifiNetwork(self, ssid: str, password: str) -> None:
        ssid = ssid.strip()
        if not ssid:
            self.alertRequested.emit("Wi-Fi", "Enter or select a Wi-Fi network first.")
            return
        if os.name == "nt":
            message = "Wi-Fi connection is available on the Raspberry Pi. Windows mode supports network scanning and status checks for UI testing."
            self._set_wifi_status("Status: Windows development mode", "#F59E0B")
            self.alertRequested.emit("Raspberry Pi Wi-Fi", message)
            return
        if self._wifi_busy:
            return
        self._set_wifi_busy(True, f"Status: Connecting to {ssid}...")
        self._wifi_status_color = "#2563EB"
        self.wifiStatusColorChanged.emit()

        def _task() -> None:
            try:
                cmd = ["nmcli", "dev", "wifi", "connect", ssid]
                if password:
                    cmd.extend(["password", password])
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=35, check=False)
                detail = (result.stderr or result.stdout or "Connection failed. Check the password.").strip()
                self.wifiConnectFinished.emit(result.returncode == 0, ssid, detail)
            except FileNotFoundError:
                self.wifiConnectFinished.emit(False, ssid, "NetworkManager utility 'nmcli' is not installed.")
            except subprocess.TimeoutExpired:
                self.wifiConnectFinished.emit(False, ssid, "Connection attempt timed out. Please try again.")
            except Exception as exc:
                self.wifiConnectFinished.emit(False, ssid, str(exc))

        threading.Thread(target=_task, daemon=True).start()

    def _finish_wifi_connect(self, success: bool, ssid: str, detail: str) -> None:
        if detail == "status-only":
            self._set_wifi_status(f"Status: Connected to {ssid}", "#10B981")
            return
        self._set_wifi_busy(False)
        if success:
            self._set_wifi_status(f"Status: Connected to {ssid}", "#10B981")
            self.alertRequested.emit("Wi-Fi Connected", f"Connected to {ssid} successfully.")
        else:
            self._set_wifi_status(f"Status: Error - {detail}", "#EF4444")
            self.alertRequested.emit("Wi-Fi Connection Failed", detail)

    @Slot()
    def refreshWifiStatus(self) -> None:
        if self._wifi_busy:
            return

        def _task() -> None:
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
                            self.wifiStatusResult.emit("Status: Raspberry Pi Wi-Fi (Windows preview)", "#F59E0B")
                            return
                        raise RuntimeError(detail)
                    connected = re.search(r"^\s*State\s*:\s*connected\s*$", result.stdout, re.MULTILINE | re.IGNORECASE)
                    ssid_match = re.search(r"^\s*SSID\s*:\s*(.+)$", result.stdout, re.MULTILINE | re.IGNORECASE)
                    if connected and ssid_match:
                        self.wifiStatusResult.emit(f"Status: Connected to {ssid_match.group(1).strip()}", "#10B981")
                    elif "There is no wireless interface" in result.stdout:
                        self.wifiStatusResult.emit("Status: No Wi-Fi adapter detected", "#F59E0B")
                    else:
                        self.wifiStatusResult.emit("Status: Disconnected", "#526176")
                    return
                result = subprocess.run(
                    ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode != 0:
                    raise RuntimeError((result.stderr or result.stdout or "Unable to check Wi-Fi status").strip())
                wifi_found = False
                for line in result.stdout.splitlines():
                    parts = line.split(":", 3)
                    if len(parts) < 4 or parts[1].strip() != "wifi":
                        continue
                    wifi_found = True
                    if parts[2].strip() == "connected":
                        self.wifiConnectFinished.emit(True, parts[3].strip(), "status-only")
                        return
                status = "Status: Disconnected" if wifi_found else "Status: Error - No Wi-Fi adapter detected"
                color = "#526176" if wifi_found else "#F59E0B"
                self.wifiStatusResult.emit(status, color)
            except FileNotFoundError:
                tool = "netsh" if os.name == "nt" else "nmcli"
                self.wifiStatusResult.emit(f"Status: Wi-Fi utility '{tool}' is not installed", "#F59E0B")
            except subprocess.TimeoutExpired:
                self.wifiStatusResult.emit("Status: Wi-Fi status check timed out", "#F59E0B")
            except Exception as exc:
                self.wifiStatusResult.emit(f"Status: Error - {exc}", "#EF4444")

        threading.Thread(target=_task, daemon=True).start()

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
            self._account_no = str(consumer.get("acct_no") or consumer["id"])
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
        rows = get_zone_consumers_with_status(self._selected_zone)
        row = next((item for item in rows if int(item.get("id", -1)) == consumer_id), None)
        if not row or not row.get("is_read"):
            self.alertRequested.emit("No Receipt", "No saved reading is available for this consumer.")
            return
        present = int(row.get("reading_value") or 0)
        consumption = int(row.get("consumption") or 0)
        previous = present - consumption
        latest_entry = get_latest_receipt_print(consumer_id)
        if latest_entry:
            receipt = latest_entry["receipt_text"]
        else:
            receipt = build_receipt_text(row, previous, present, row.get("exception") or "None", self._reader_name)
            latest_entry = {
                "consumer_id": consumer_id,
                "reading_id": None,
                "acct_no": row.get("acct_no"),
                "consumer_name": row.get("name"),
                "meter_no": row.get("meter_no"),
                "zone_name": row.get("zone_name", self._selected_zone),
                "previous_reading": previous,
                "present_reading": present,
                "consumption": consumption,
                "exception": row.get("exception") or "None",
                "reader_name": self._reader_name,
                "receipt_text": receipt,
            }
        if can_use_system_printer():
            try:
                send_to_system_printer(receipt)
            except Exception as exc:
                self.alertRequested.emit("Printer Error", f"Unable to print to the GP58 over USB.\n\n{exc}")
        saved_id = save_receipt_print(
            latest_entry["consumer_id"],
            latest_entry["receipt_text"],
            int(latest_entry["previous_reading"]),
            int(latest_entry["present_reading"]),
            int(latest_entry["consumption"]),
            latest_entry.get("exception") or "None",
            latest_entry.get("reader_name") or self._reader_name,
            latest_entry.get("reading_id"),
            "reprint",
            latest_entry.get("acct_no"),
            latest_entry.get("consumer_name"),
            latest_entry.get("meter_no"),
            latest_entry.get("zone_name"),
        )
        self._last_receipt_entry = {**latest_entry, "id": saved_id, "print_action": "reprint"}
        self._last_receipt = latest_entry["receipt_text"]
        self.canReprintChanged.emit()
        self.receiptPreviewRequested.emit("Receipt Preview", receipt)

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

    def _set_print_preview_busy(self, busy: bool) -> None:
        if self._print_preview_busy != busy:
            self._print_preview_busy = busy
            self.printPreviewBusyChanged.emit()

    def _open_print_preview(self, title: str, receipt_text: str, action_label: str, job: dict) -> None:
        self._pending_print_job = dict(job)
        self.printPreviewRequested.emit(title, receipt_text, action_label)

    def _build_pending_receipt_job(self) -> dict:
        self._reload_current_consumer_from_db()
        present = int(self._present_reading)
        previous = int(self._consumer["previous_reading"])
        consumption = present - previous
        exception = self._selected_exception
        receipt = build_receipt_text(self._consumer, previous, present, exception, self._reader_name)
        return {
            "job_type": "original",
            "consumer_snapshot": dict(self._consumer),
            "consumer_id": self._consumer["id"],
            "previous": previous,
            "present": present,
            "consumption": consumption,
            "exception": exception,
            "receipt_text": receipt,
            "reader_name": self._reader_name,
        }

    @Slot()
    def printReceipt(self) -> None:
        if not self._consumer or not self._present_reading:
            self.alertRequested.emit("Missing Details", "Select a consumer and enter a present reading.")
            return

        try:
            self._reload_current_consumer_from_db()
            present = int(self._present_reading)
            previous = int(self._consumer["previous_reading"])
            if present < previous:
                self.alertRequested.emit("Invalid Reading", "Present reading cannot be lower than the previous reading.")
                return
            if self._paper_status.lower() in {"out", "jam"}:
                self.alertRequested.emit("Paper Error", f"Cannot print while paper status is {self._paper_status}.")
                return
            job = self._build_pending_receipt_job()
            self._open_print_preview("Print Preview", job["receipt_text"], "Proceed to Print", job)
        except Exception as e:
            self.alertRequested.emit("Save Failed", str(e))

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
        if not self._last_receipt_entry:
            self._last_receipt_entry = get_latest_receipt_print()
            self._last_receipt = self._last_receipt_entry["receipt_text"] if self._last_receipt_entry else None
        if not self._last_receipt_entry:
            self.alertRequested.emit("No Receipt", "No saved receipt is available for reprint.")
            return
        if self._paper_status.lower() in {"out", "jam"}:
            self.alertRequested.emit("Paper Error", f"Cannot print while paper status is {self._paper_status}.")
            return
        original_printed_at = str(self._last_receipt_entry.get("printed_at") or "")
        preview_text = build_reprint_receipt_text(
            self._last_receipt_entry["receipt_text"],
            original_printed_at=original_printed_at,
        )
        job = {
            "job_type": "reprint",
            "source_entry": dict(self._last_receipt_entry),
            "receipt_text": preview_text,
        }
        self._open_print_preview("Reprint Preview", preview_text, "Proceed to Reprint", job)

    @Slot()
    def syncNow(self) -> None:
        if not self._sync_dal:
            self.alertRequested.emit("Sync Unavailable", self._sync_logs)
            return
        self._set_operation_busy(True, "Syncing...")

        def _task() -> None:
            try:
                result = self._sync_dal.syncPendingReadings()
                consumers = self._sync_dal.loadAssignedConsumers(None)
                mirrored = replace_consumers_from_sync(consumers)
                self.syncTaskFinished.emit({"kind": "sync", "result": result, "mirrored": mirrored})
            except Exception as exc:
                self.syncTaskFinished.emit({"kind": "error", "error": str(exc)})

        threading.Thread(target=_task, daemon=True).start()

    @Slot()
    def printTestReceipt(self) -> None:
        if self._test_print_busy:
            return

        self._test_print_busy = True
        self.testPrintBusyChanged.emit()

        def _task() -> None:
            try:
                preview_text = print_test_receipt()
                self.testPrintFinished.emit(True, preview_text)
            except Exception as exc:
                self.testPrintFinished.emit(False, str(exc) or "Unknown printer error.")

        threading.Thread(target=_task, daemon=True).start()

    def _finish_test_print(self, success: bool, payload: str) -> None:
        self._test_print_busy = False
        self.testPrintBusyChanged.emit()
        if success:
            self.alertRequested.emit("Printer Test", "Test print sent successfully.")
            self.receiptPreviewRequested.emit("Test Print Preview", payload)
            return

        detail = payload.strip()
        friendly = "Unable to print. Please check that the thermal printer is connected and powered on."
        if detail:
            friendly = f"{friendly}\n\nDetails: {detail}"
        self.alertRequested.emit("Printer Error", friendly)

    @Slot()
    def cancelPrintPreview(self) -> None:
        self._pending_print_job = None
        self._set_print_preview_busy(False)

    @Slot()
    def proceedPrintPreview(self) -> None:
        if self._print_preview_busy or not self._pending_print_job:
            return

        job = dict(self._pending_print_job)

        if job.get("job_type") != "original" and not can_use_system_printer():
            self.alertRequested.emit(
                "Printer Error",
                "Unable to print. Please check that the thermal printer is connected, powered on, and ready.",
            )
            return

        self._set_print_preview_busy(True)
        self._set_operation_busy(True, "Printing...")

        def _task() -> None:
            try:
                receipt_text = job["receipt_text"]

                if job.get("job_type") == "original":
                    consumer = dict(job["consumer_snapshot"])
                    present = int(job["present"])
                    previous = int(job["previous"])
                    consumption = int(job["consumption"])
                    exception = str(job["exception"])
                    flagged = consumption > 500 or exception != "None"
                    reading_id = save_reading(job["consumer_id"], present, consumption, exception, flagged)
                    self._save_to_sync_layer(job["consumer_id"], present, consumption, exception, flagged)
                    saved_receipt_id = save_receipt_print(
                        job["consumer_id"],
                        receipt_text,
                        previous,
                        present,
                        consumption,
                        exception,
                        job.get("reader_name") or self._reader_name,
                        reading_id,
                        "print",
                        consumer.get("acct_no"),
                        consumer.get("name"),
                        consumer.get("meter_no"),
                        consumer.get("zone_name", self._selected_zone),
                    )
                    print_error = None
                    if can_use_system_printer():
                        try:
                            send_to_system_printer(receipt_text)
                        except Exception as exc:
                            print_error = str(exc)
                    else:
                        print_error = "Printer device is unavailable."
                    self.printExecutionFinished.emit(
                        {
                            "success": True,
                            "job_type": "original",
                            "printed": print_error is None,
                            "print_error": print_error,
                            "saved_receipt_id": saved_receipt_id,
                            "reading_id": reading_id,
                            "consumer_snapshot": consumer,
                            "previous": previous,
                            "present": present,
                            "consumption": consumption,
                            "exception": exception,
                            "receipt_text": receipt_text,
                        }
                    )
                    return

                send_to_system_printer(receipt_text)
                source_entry = dict(job["source_entry"])
                saved_id = save_receipt_print(
                    source_entry["consumer_id"],
                    receipt_text,
                    int(source_entry["previous_reading"]),
                    int(source_entry["present_reading"]),
                    int(source_entry["consumption"]),
                    source_entry.get("exception") or "None",
                    self._reader_name,
                    source_entry.get("reading_id"),
                    "reprint",
                    source_entry.get("acct_no"),
                    source_entry.get("consumer_name"),
                    source_entry.get("meter_no"),
                    source_entry.get("zone_name"),
                )
                self.printExecutionFinished.emit(
                    {
                        "success": True,
                        "job_type": "reprint",
                        "saved_receipt_id": saved_id,
                        "source_entry": source_entry,
                        "receipt_text": receipt_text,
                    }
                )
            except Exception as exc:
                self.printExecutionFinished.emit({"success": False, "error": str(exc)})

        threading.Thread(target=_task, daemon=True).start()

    def _finish_print_execution(self, result: dict) -> None:
        self._set_print_preview_busy(False)
        self._set_operation_busy(False, "")
        if not result.get("success"):
            self.alertRequested.emit(
                "Printer Error",
                "Unable to print. Please check that the thermal printer is connected, powered on, and ready."
                + (f"\n\nDetails: {result.get('error')}" if result.get("error") else ""),
            )
            return

        self._pending_print_job = None
        if result.get("job_type") == "original":
            consumer = dict(result["consumer_snapshot"])
            present = int(result["present"])
            self._last_receipt_entry = {
                "id": result["saved_receipt_id"],
                "consumer_id": consumer["id"],
                "reading_id": result["reading_id"],
                "acct_no": consumer.get("acct_no"),
                "consumer_name": consumer.get("name"),
                "meter_no": consumer.get("meter_no"),
                "zone_name": consumer.get("zone_name", self._selected_zone),
                "previous_reading": int(result["previous"]),
                "present_reading": present,
                "consumption": int(result["consumption"]),
                "exception": result.get("exception") or "None",
                "reader_name": self._reader_name,
                "receipt_text": result["receipt_text"],
                "print_action": "print",
            }
            self._last_receipt = result["receipt_text"]
            self.canReprintChanged.emit()
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
            self.refreshPrintHistory()
            if result.get("printed", True):
                self.alertRequested.emit("Print Complete", "Receipt printed successfully.")
            else:
                self.alertRequested.emit(
                    "Reading Saved",
                    "Reading saved successfully, but printing failed."
                    + (f"\n\nDetails: {result.get('print_error')}" if result.get("print_error") else ""),
                )
            return

        source_entry = dict(result["source_entry"])
        self._last_receipt_entry = {**source_entry, "id": result["saved_receipt_id"], "print_action": "reprint", "receipt_text": result["receipt_text"]}
        self._last_receipt = result["receipt_text"]
        self.canReprintChanged.emit()
        self.refreshPrintHistory()
        self.alertRequested.emit("Reprint Complete", "Receipt reprinted successfully.")

    @Slot()
    def openPrintHistory(self) -> None:
        self.refreshPrintHistory()
        self.printHistoryRequested.emit()

    @Slot(str)
    def refreshPrintHistory(self, search_text: str = "") -> None:
        rows = list_receipt_print_history(search_text=search_text, limit=200)
        self._print_history_records = [
            {
                "id": row.get("id"),
                "receipt_number": f"{int(row.get('id', 0)):06d}" if row.get("id") else "",
                "receipt_type": "Receipt",
                "account_number": row.get("acct_no") or "",
                "consumer_name": row.get("consumer_name") or "",
                "billing_period": row.get("zone_name") or "",
                "total_amount": row.get("consumption") or 0,
                "printed_at": row.get("printed_at") or "",
                "printed_by": row.get("reader_name") or "",
                "print_count": row.get("print_count") or 1,
                "reprint_count": row.get("reprint_count") or 0,
                "print_action": row.get("print_action") or "print",
            }
            for row in rows
        ]
        self.printHistoryRecordsChanged.emit()

    @Slot(int)
    def openPrintHistoryDetail(self, receipt_print_id: int) -> None:
        self._print_history_detail = get_receipt_print_by_id(receipt_print_id)
        self.printHistoryDetailChanged.emit()

    @Slot()
    def closePrintHistoryDetail(self) -> None:
        self._print_history_detail = None
        self.printHistoryDetailChanged.emit()

    @Slot()
    def reprintSelectedHistory(self) -> None:
        if not self._print_history_detail:
            return
        if self._paper_status.lower() in {"out", "jam"}:
            self.alertRequested.emit("Paper Error", f"Cannot print while paper status is {self._paper_status}.")
            return
        preview_text = build_reprint_receipt_text(
            self._print_history_detail["receipt_text"],
            original_printed_at=str(self._print_history_detail.get("printed_at") or ""),
        )
        self._open_print_preview(
            "Reprint Preview",
            preview_text,
            "Proceed to Reprint",
            {
                "job_type": "reprint",
                "source_entry": dict(self._print_history_detail),
                "receipt_text": preview_text,
            },
        )

    @Slot()
    def powerOffDevice(self) -> None:
        if os.name == "nt":
            self.alertRequested.emit(
                "Windows Preview",
                "Safe power-off is intended for the Raspberry Pi device.\n\n"
                "On the Pi, this button will request a graceful OS shutdown before external power is removed.",
            )
            return

        self._set_operation_busy(True, "Syncing before power off...")

        def _task() -> None:
            try:
                if self._sync_dal:
                    result = self._sync_dal.syncPendingReadings()
                    if result.get("status") != "done":
                        detail = str(result.get("error") or result.get("status") or "Sync failed before shutdown.")
                        self.powerOffFailed.emit(f"Shutdown cancelled because sync did not complete cleanly.\n\n{detail}")
                        return

                    pending_after_sync = len(self._sync_dal.listPendingSyncReadings())
                    if pending_after_sync > 0:
                        self.powerOffFailed.emit(
                            f"Shutdown cancelled because {pending_after_sync} reading(s) are still pending after sync."
                        )
                        return

                    consumers = self._sync_dal.loadAssignedConsumers(None)
                    mirrored = replace_consumers_from_sync(consumers)
                    self.syncTaskFinished.emit(
                        {"kind": "sync", "result": result, "mirrored": mirrored, "silent": True, "keep_busy": True}
                    )
            except Exception as exc:
                self.powerOffFailed.emit(
                    f"Shutdown cancelled because the pre-shutdown sync failed.\n\n{str(exc) or 'Unknown sync error.'}"
                )
                return

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

            self.powerOffFailed.emit(last_error)

        threading.Thread(target=_task, daemon=True).start()

    def _finish_power_off_failure(self, detail: str) -> None:
        self._set_operation_busy(False, "")
        self.alertRequested.emit(
            "Shutdown Cancelled",
            detail,
        )

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
        self.quick.setSource(QUrl.fromLocalFile(str(QML_LOGIN_FILE)))
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
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
        self.quick.setSource(QUrl.fromLocalFile(str(QML_MAIN_FILE)))
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        layout.addWidget(self.quick)




class HybridMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Water Meter Reader - Qt Hybrid")
        self.resize(480, 800)  # Match the portrait touchscreen viewport more closely.

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



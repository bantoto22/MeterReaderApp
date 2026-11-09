import gc
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import database
from src.handheld_sync import HandheldSyncDataAccess, SQLiteLocalSyncStore, SyncConfig
from src.qt_hybrid_app import AppBridge


class ImmediateThread:
    def __init__(self, *, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class AssignmentBackend:
    def __init__(self):
        self._url = "https://device.example.test/api"
        self.online = True
        self.schedule_error = None
        self.consumer_error = None
        self.windows = []
        self.schedule = {
            "schedule_id": 202, "meter_reader_id": 12, "zone_name": "Zone 1",
            "start_date": "2026-12-01", "due_date": "2026-12-07",
            "billing_month": "December 2026", "status": "Scheduled",
        }

    def is_online(self):
        return self.online

    def load_reading_schedules(self, reader, date_from, date_to, status):
        self.windows.append((date_from, date_to))
        if self.schedule_error:
            raise RuntimeError(self.schedule_error)
        if status == "Scheduled" and date_from <= self.schedule["start_date"] <= date_to:
            return [dict(self.schedule)]
        return []

    def load_assigned_consumers(self, reader, zone, date_from, date_to):
        if self.consumer_error:
            raise RuntimeError(self.consumer_error)
        if date_from <= self.schedule["start_date"] <= date_to:
            return [{
                "id": 1, "meter_no": "MTR-1", "acct_no": "ACCT-1",
                "name": "Consumer 1", "zone_name": "Zone 1",
                "schedule_id": 202, "is_read": False,
            }]
        return []

    def get_consumer_context(self, consumer_id):
        return {"id": consumer_id, "name": "Consumer 1"}


class AssignmentRefreshTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = str(Path(directory.name) / "meter.db")
        db_patch = patch.object(database, "_db_path", return_value=path)
        db_patch.start()
        self.addCleanup(db_patch.stop)
        self.addCleanup(gc.collect)
        database.init_db()
        self.remote = AssignmentBackend()
        self.store = SQLiteLocalSyncStore(SyncConfig())
        self.store._db_path = path
        self.dal = HandheldSyncDataAccess(self.store, self.remote)
        self.today_patch = patch("src.qt_hybrid_app.manila_current_date", return_value=date(2026, 11, 7))
        self.today_patch.start()
        self.addCleanup(self.today_patch.stop)
        thread_patch = patch("src.qt_hybrid_app.threading", SimpleNamespace(Thread=ImmediateThread))
        thread_patch.start()
        self.addCleanup(thread_patch.stop)
        old = {
            "schedule_id": 101, "meter_reader_id": 12, "zone_name": "Zone 1",
            "start_date": "2026-08-01", "due_date": "2026-08-07", "status": "Scheduled",
        }
        self.store.cache_reading_schedules([old], 12, "2026-08-01", "2026-08-31")
        cached = {"id": 1, "meter_no": "MTR-1", "name": "Consumer 1",
                  "zone_name": "Zone 1", "schedule_id": 101, "is_read": False}
        self.store.cache_consumers([cached])
        database.replace_consumers_from_sync([cached])

    def view(self):
        view = SimpleNamespace(
            _sync_dal=self.dal, _meter_reader_account_id="12",
            _backend_endpoint=self.remote._url, _operation_busy=False,
            _backend_status="Online", _emit_sync_state=Mock(), _start_heartbeat=Mock(),
            _auto_sync_enabled=True, _assigned_dataset_refreshing=False,
            _selected_reading_date=lambda: date(2026, 8, 7),
            _set_operation_busy=Mock(), _refresh_sync_snapshot=Mock(),
            _reload_current_consumer_from_db=Mock(), _sync_review_count=0,
            _last_pull_count=0, _last_pull_mirror=0, _zone_refreshing=set(),
            _zone_refresh_attempted=set(), _assigned_routes=[], _selected_route_id="",
            _route_selected_by_user=False, _zones=[], _selected_zone="",
            _selected_route_billing_date="", _refresh_search_suggestions=Mock(),
            _refresh_zone_consumers=Mock(), update_stats=Mock(),
            alertRequested=SimpleNamespace(emit=Mock()),
            syncTaskFinished=SimpleNamespace(emit=Mock()),
            assignedDatasetFinished=SimpleNamespace(emit=Mock()),
        )
        for name in ("assignedRoutesChanged", "selectedRouteChanged", "zonesChanged",
                     "selectedZoneChanged", "lastPullCountChanged", "lastPullMirrorChanged",
                     "syncLogsChanged", "backendLogsChanged"):
            setattr(view, name, SimpleNamespace(emit=Mock()))
        view._selected_route = lambda: next(
            (row for row in view._assigned_routes if row["scheduleId"] == view._selected_route_id), {}
        )
        view._refresh_local_assignment_views = lambda: AppBridge._refresh_local_assignment_views(view)
        view._verify_cached_routes = lambda zones: AppBridge._verify_cached_routes(view, zones)
        view._mirror_assigned_schedules = lambda *args: AppBridge._mirror_assigned_schedules(view, *args)
        view._start_assigned_consumer_dataset_refresh = lambda: AppBridge._start_assigned_consumer_dataset_refresh(view)
        view.syncTaskFinished.emit.side_effect = lambda result: AppBridge._finish_sync_task(view, result)
        view.assignedDatasetFinished.emit.side_effect = lambda result: AppBridge._finish_assigned_consumer_dataset(view, result)
        return view

    def assert_new_assignment_downloaded(self):
        self.assertIn(202, {row["schedule_id"] for row in database.get_assigned_routes(12)})
        rows = database.get_zone_consumers_with_status("Zone 1", meter_reader_id=12, schedule_id=202)
        self.assertEqual([row["id"] for row in rows], [1])
        self.assertTrue(all(window == ("2025-11-01", "2026-12-31") for window in self.remote.windows))

    def test_manual_sync_discovers_new_schedule_while_viewing_old_route(self):
        view = self.view()
        AppBridge.syncNow(view)
        self.assert_new_assignment_downloaded()
        result = view.syncTaskFinished.emit.call_args.args[0]
        self.assertEqual(result["kind"], "sync")
        self.assertEqual(result["pulled"], 1)
        self.assertNotIn("pull_error", result["result"])
        self.assertTrue(any(schedule["scheduleId"] == "202" for route in view._assigned_routes
                            for schedule in route["schedules"]))
        self.assertEqual(view.alertRequested.emit.call_args.args[0], "Sync Complete")

    def test_auto_pull_discovers_new_schedule_with_no_pending_uploads(self):
        self.assertEqual(self.dal.listPendingBackendReadings(), [])
        view = self.view()
        AppBridge._run_auto_pull(view)
        self.assert_new_assignment_downloaded()
        self.assertTrue(view.assignedDatasetFinished.emit.call_args.args[0]["success"])
        self.assertFalse(view._assigned_dataset_refreshing)
        self.assertTrue(any(schedule["scheduleId"] == "202" for route in view._assigned_routes
                            for schedule in route["schedules"]))

    def test_zone_refresh_discovers_new_assignment_while_viewing_old_route(self):
        view = self.view()
        view._zone_refreshing = set()
        view._zone_refresh_attempted = set()
        AppBridge._start_selected_zone_consumer_refresh(view, "Zone 1")
        self.assert_new_assignment_downloaded()

    def test_manual_sync_reports_schedule_download_error(self):
        self.remote.schedule_error = "HTTP 401 /api/reading-schedules: session expired"
        view = self.view()
        AppBridge.syncNow(view)
        result = view.syncTaskFinished.emit.call_args.args[0]
        self.assertIn("HTTP 401", result["result"].get("pull_error", ""))
        self.assertEqual(result["pulled"], 0)
        self.assertEqual(self.store.load_cached_consumers()[0]["schedule_id"], 101)
        self.assertEqual(view.alertRequested.emit.call_args.args[0], "Sync Finished with Problems")

    def test_manual_sync_reports_consumer_download_error_instead_of_cached_success(self):
        self.remote.consumer_error = "HTTP 503 /api/handheld/consumers: unavailable"
        view = self.view()
        AppBridge.syncNow(view)
        result = view.syncTaskFinished.emit.call_args.args[0]
        self.assertIn("HTTP 503", result["result"].get("pull_error", ""))
        self.assertEqual(result["pulled"], 0)
        self.assertEqual(self.store.load_cached_consumers()[0]["schedule_id"], 101)

    def test_offline_sync_does_not_report_cached_rows_as_downloaded(self):
        self.remote.online = False
        view = self.view()
        AppBridge.syncNow(view)
        result = view.syncTaskFinished.emit.call_args.args[0]
        self.assertTrue(result["result"].get("pull_error"))
        self.assertEqual(result["pulled"], 0)
        self.assertEqual(len(database.get_assigned_routes(12)), 1)
        self.assertEqual(self.dal.loadAssignedConsumers(12)[0]["schedule_id"], 101)

    def test_auto_pull_reports_failure_and_preserves_local_route(self):
        self.remote.consumer_error = "HTTP 503 /api/handheld/consumers: unavailable"
        view = self.view()
        AppBridge._run_auto_pull(view)
        result = view.assignedDatasetFinished.emit.call_args.args[0]
        self.assertFalse(result["success"])
        self.assertIn("HTTP 503", result["error"])
        self.assertFalse(view._assigned_dataset_refreshing)
        self.assertEqual(self.store.load_cached_consumers()[0]["schedule_id"], 101)
        self.assertTrue(any("HTTP 503" in entry["message"] for entry in self.dal.get_recent_audit_entries()))

    def test_empty_download_does_not_count_cached_assignments_as_pulled(self):
        self.remote.schedule["start_date"] = "2027-02-01"
        view = self.view()
        AppBridge.syncNow(view)
        result = view.syncTaskFinished.emit.call_args.args[0]
        self.assertEqual(result["pulled"], 0)
        self.assertNotIn("pull_error", result["result"])
        self.assertEqual(self.store.load_cached_consumers()[0]["schedule_id"], 101)

    def test_download_failure_stays_visible_when_backend_health_is_online(self):
        self.remote.consumer_error = "HTTP 401 /api/handheld/consumers: session expired"
        view = self.view()
        AppBridge.syncNow(view)
        AppBridge._refresh_sync_snapshot(view, self.dal.get_sync_snapshot())
        self.assertEqual(view._sync_status, "Sync Failed")
        self.assertIn("cached", view._assignment_download_status.lower())
        self.assertIn("HTTP 401", view._sync_logs)
        self.assertIn("Assignment download:", view._sync_logs)
        self.remote.consumer_error = None
        AppBridge.syncNow(view)
        AppBridge._refresh_sync_snapshot(view, self.dal.get_sync_snapshot())
        self.assertEqual(view._sync_status, "Online")
        self.assertEqual(view._assignment_download_error, "")
        self.assertEqual(view._assignment_download_status, "Fresh backend data")

    def test_upload_only_completion_does_not_change_last_download_counts(self):
        view = self.view()
        view._last_pull_count = 75
        view._last_pull_mirror = 75
        AppBridge._finish_sync_task(view, {"kind": "sync", "silent": True, "result": {}, "mirrored": 0})
        self.assertEqual((view._last_pull_count, view._last_pull_mirror), (75, 75))

    def test_consumer_context_does_not_overwrite_assignment_read_flags(self):
        self.store.cache_consumers([{
            "id": 1, "meter_no": "MTR-1", "zone_name": "Zone 1", "schedule_id": 202,
            "is_read": True, "reading_status": "Recorded", "reading_sync_status": "synced",
        }])
        self.remote.get_consumer_context = lambda _id: {
            "previous_reading": 42, "is_read": False, "reading_status": "pending",
            "bill": {"schedule_id": 202, "amount_due": 100},
        }
        result = self.dal.prefetchAssignedConsumerContexts([{"id": 1}])
        self.assertEqual(result["refreshed"], 1)
        assignments = {row["schedule_id"]: row for row in self.store.load_cached_consumers()}
        self.assertEqual(assignments[101]["is_read"], 0)
        self.assertEqual(assignments[202]["is_read"], 1)
        self.assertEqual(assignments[202]["reading_status"], "Recorded")
        self.assertEqual(assignments[202]["previous_reading"], 42)

    def test_repeated_sync_of_156_assignments_does_not_add_consumers_or_readings(self):
        schedules = [{
            "schedule_id": 500 + month, "meter_reader_id": 12, "zone_name": "Zone 1",
            "start_date": f"2026-{month:02d}-01", "due_date": f"2026-{month:02d}-07",
            "billing_month": f"2026-{month:02d}", "status": "Scheduled",
        } for month in range(1, 13)]
        rows = [{
            "id": consumer_id, "meter_no": f"MTR-{consumer_id}", "name": f"Consumer {consumer_id}",
            "zone_name": "Zone 1", "schedule_id": schedule["schedule_id"], "is_read": False,
            "latest_reading": 100 + consumer_id, "latest_reading_date": "2026-11-07",
        } for schedule in schedules for consumer_id in range(1, 14)]
        self.remote.load_reading_schedules = lambda _reader, _start, _end, status: schedules if status == "Scheduled" else []
        self.remote.load_assigned_consumers = lambda *args: rows
        view = self.view()
        for _ in range(2):
            AppBridge.syncNow(view)
            result = view.syncTaskFinished.emit.call_args.args[0]
            self.assertEqual((result["pulled"], result["mirrored"]), (156, 156))
            self.assertIn("Unique consumers: 13", view._assignment_download_summary)
            self.assertIn("Schedules: 12", view._assignment_download_summary)
            self.assertIn("Repeated assignment rows: 0", view._assignment_download_summary)
            connection = database.get_connection()
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM consumers").fetchone()[0], 13)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM reading_assignment WHERE schedule_id BETWEEN 501 AND 512").fetchone()[0], 156)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM handheld_assignments_cache WHERE schedule_id BETWEEN 501 AND 512").fetchone()[0], 156)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 13)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM sync_queue_meter_readings").fetchone()[0], 0)
            finally:
                connection.close()

    def test_duplicate_response_rows_are_reported_without_duplicating_assignments(self):
        rows = [{
            "id": consumer_id, "meter_no": f"MTR-{consumer_id}", "name": f"Consumer {consumer_id}",
            "zone_name": "Zone 1", "schedule_id": 202, "is_read": False,
        } for consumer_id in (1, 2)]
        self.remote.load_assigned_consumers = lambda *args: rows + rows
        view = self.view()
        AppBridge.syncNow(view)
        self.assertIn("Unique consumers: 2", view._assignment_download_summary)
        self.assertIn("Schedules: 1", view._assignment_download_summary)
        self.assertIn("Repeated assignment rows: 2", view._assignment_download_summary)
        connection = database.get_connection()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reading_assignment WHERE schedule_id=202").fetchone()[0], 2)
        finally:
            connection.close()

    def test_243_pulled_146_mirrored_reports_97_rows_without_real_meters(self):
        rows = [{
            "id": consumer_id, "meter_no": f"MTR-{consumer_id}", "name": f"Consumer {consumer_id}",
            "zone_name": "Zone 1", "schedule_id": 202, "is_read": False,
        } for consumer_id in range(1, 244)]
        for row in rows[146:196]:
            row["meter_no"] = None
        for row in rows[196:]:
            row["meter_no"] = f"ACCT-{row['id']}"
        self.remote.load_assigned_consumers = lambda *args: rows
        self.dal.prefetchAssignedConsumerContexts = Mock(return_value={})
        view = self.view()
        for mode in ("manual", "automatic"):
            with self.subTest(mode=mode):
                if mode == "manual":
                    AppBridge.syncNow(view)
                    result = view.syncTaskFinished.emit.call_args.args[0]
                    self.assertEqual(result["result"]["skipped_records"], 97)
                    self.assertEqual(view.alertRequested.emit.call_args.args[0], "Sync Finished with Problems")
                else:
                    AppBridge._run_auto_pull(view)
                    result = view.assignedDatasetFinished.emit.call_args.args[0]
                    self.assertEqual(result["skipped_records"], 97)
                self.assertEqual((result["pulled"], result["mirrored"]), (243, 146))
                self.assertIn("Skipped rows: 97", view._assignment_download_summary)
                self.assertIn("Missing meter number: 50", view._assignment_download_summary)
                self.assertIn("Placeholder meter number: 47", view._assignment_download_summary)
                self.assertIn("97 rows skipped", view._assignment_download_status)
                connection = database.get_connection()
                try:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM consumers").fetchone()[0], 146)
                finally:
                    connection.close()
        self.assertTrue(any(entry.get("payload", {}).get("skipped") == 97
                            for entry in self.dal.get_recent_audit_entries()))


if __name__ == "__main__":
    unittest.main()

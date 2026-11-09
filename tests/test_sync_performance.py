import gc
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import database
from src.handheld_sync import BackendApiClient, BackendRequestError, HandheldSyncDataAccess, SQLiteLocalSyncStore, SyncConfig
from src.qt_hybrid_app import AppBridge


class InlineThread:
    def __init__(self, *, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class CountingBackend(BackendApiClient):
    def __init__(self):
        super().__init__(SyncConfig(backend_api_base_url="https://example.test/api", device_id="TEST-DEVICE"))
        self.set_authenticated_session("test-session", 12)
        self.requests = []
        self.reservations = {}
        self.reserve_failure = None
        self.schedule_failure = None
        self.consumers = [{
            "id": i, "consumer_id": i, "meter_no": f"TEST-{i}", "acct_no": f"ACCOUNT-{i}",
            "name": f"Consumer {i}", "zone_name": "Zone 1", "schedule_id": 401,
            "schedule_date": "2026-11-09", "schedule_due_date": "2026-11-11",
            "billing_cycle": "November 2026", "is_read": False,
        } for i in range(1, 4)]

    def _req(self, method, path, *, query=None, payload=None, **kwargs):
        self.requests.append((method, path, query))
        if path == "/health":
            return 200, {"status": "ok"}
        if path == "/api/reading-schedules":
            if self.schedule_failure:
                return self.schedule_failure, {"error": "schedule lookup failed"}
            return 200, [{
                "schedule_id": 401, "meter_reader_id": 12, "zone_name": "Zone 1",
                "start_date": "2026-11-09", "due_date": "2026-11-11", "status": "Scheduled",
            }, {
                "schedule_id": 400, "meter_reader_id": 12, "zone_name": "Zone 1",
                "start_date": "2026-11-01", "due_date": "2026-11-02", "status": "Cancelled",
            }]
        if path == "/api/handheld/consumers":
            return 200, list(self.consumers)
        if path == "/api/handheld/billing-references/reserve":
            failure, self.reserve_failure = self.reserve_failure, None
            if failure is not None and failure != 0:
                return failure, {"error": "reservation rejected"}
            sync_id = payload["bill_sync_id"]
            if sync_id not in self.reservations:
                self.reservations[sync_id] = {
                    "billing_reference": f"SLR2026{len(self.reservations) + 1:06d}",
                    "bill_date": payload["bill_date"],
                }
            if failure == 0:
                return 0, {"error": "Temporary failure in name resolution after a lost response"}
            return 200, {"success": True, **self.reservations[sync_id]}
        if path.endswith("/context"):
            return 200, {"id": int(path.split("/")[-2]), "previous_reading_date": "2026-10-09"}
        raise AssertionError(f"Unexpected request: {method} {path}")

    def count(self, path):
        return sum(request[1] == path for request in self.requests)


class SyncPerformanceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(gc.collect)
        path = str(Path(directory.name) / "meter.db")
        db_path = patch.object(database, "_db_path", return_value=path)
        db_path.start()
        self.addCleanup(db_path.stop)
        database.init_db()
        self.remote = CountingBackend()
        store = SQLiteLocalSyncStore(SyncConfig())
        store._db_path = path
        self.dal = HandheldSyncDataAccess(store, self.remote)
        today = patch("src.handheld_sync._manila_current_date", return_value=date(2026, 11, 9))
        today.start()
        self.addCleanup(today.stop)

    def view(self):
        view = SimpleNamespace(
            _sync_dal=self.dal, _meter_reader_account_id="12", _backend_endpoint="https://example.test/api",
            _operation_busy=False, _assigned_dataset_refreshing=False, _set_operation_busy=Mock(),
            syncTaskFinished=Mock(), syncProgress=Mock(), alertRequested=Mock(),
        )
        view._mirror_assigned_schedules = lambda *args: AppBridge._mirror_assigned_schedules(view, *args)
        return view

    def sync(self, view):
        with patch("src.qt_hybrid_app.threading", SimpleNamespace(Thread=InlineThread)), patch(
            "src.qt_hybrid_app._assignment_download_window", return_value=("2026-11-01", "2026-11-30")
        ):
            AppBridge.syncNow(view)
        return view.syncTaskFinished.emit.call_args.args[0]

    def test_manual_sync_downloads_schedules_once_including_cancelled_and_reports_progress(self):
        view = self.view()
        result = self.sync(view)
        self.assertEqual(result["kind"], "sync")
        self.assertEqual(result["pulled"], 3)
        self.assertEqual(self.remote.count("/api/reading-schedules"), 1)
        schedule_request = next(row for row in self.remote.requests if row[1] == "/api/reading-schedules")
        self.assertNotIn("status", schedule_request[2])
        self.assertEqual(self.remote.count("/health"), 2)
        self.assertEqual(self.remote.count("/api/handheld/billing-references/reserve"), 9)
        self.assertEqual(result["result"]["offline_references_ready"], 9)
        self.assertEqual(result["context_pull"]["refreshed"], 3)
        messages = [call.args[0] for call in view.syncProgress.emit.call_args_list]
        self.assertIn("Preparing offline references: 9 ready, 0 problems", messages)
        self.assertIn("Downloading offline records: 3/3", messages)
        conn = database.get_connection()
        try:
            self.assertEqual(conn.execute("SELECT status FROM reading_schedule WHERE schedule_id=400").fetchone()[0], "Cancelled")
        finally:
            conn.close()

    def test_repeat_sync_reuses_every_exact_reference_without_new_reservations(self):
        self.sync(self.view())
        original = dict(self.remote.reservations)
        self.remote.requests.clear()
        result = self.sync(self.view())
        self.assertEqual(self.remote.count("/api/reading-schedules"), 1)
        self.assertEqual(self.remote.count("/api/handheld/billing-references/reserve"), 0)
        self.assertEqual(result["result"]["offline_references_ready"], 9)
        self.assertEqual(original, self.remote.reservations)

    def test_reference_batch_checks_health_once_instead_of_once_per_date(self):
        result = self.dal.preReserveAssignedBills(self.remote.consumers, through_date="2026-11-30")
        self.assertEqual(result["ready"], 9)
        self.assertEqual(self.remote.count("/health"), 1)

    def test_lost_reservation_response_stops_batch_and_retry_uses_same_uuid(self):
        self.remote.reserve_failure = 0
        result = self.dal.preReserveAssignedBills(self.remote.consumers, through_date="2026-11-30")
        self.assertTrue(result["stopped_early"])
        self.assertEqual(result["failed"], 1)
        self.assertEqual(self.remote.count("/api/handheld/billing-references/reserve"), 1)
        original_id, original = next(iter(self.remote.reservations.items()))
        draft = self.dal.local.get_or_create_bill_reservation(1, "2026-11-09", schedule_id=401)
        self.assertEqual(draft["bill_sync_id"], original_id)
        self.assertFalse(draft["billing_reference"])
        self.remote.requests.clear()
        retried = self.dal.preReserveAssignedBills(self.remote.consumers, through_date="2026-11-30")
        self.assertEqual((retried["ready"], retried["failed"]), (9, 0))
        self.assertEqual(self.remote.reservations[original_id], original)
        self.assertEqual(len(self.remote.reservations), 9)
        saved = self.dal.local.get_or_create_bill_reservation(1, "2026-11-09", schedule_id=401)
        self.assertEqual(saved["billing_reference"], original["billing_reference"])

    def test_global_api_rejection_stops_reference_batch_without_repeated_requests(self):
        for status in (401, 403, 429, 503):
            with self.subTest(status=status):
                self.remote.requests.clear()
                self.remote.reserve_failure = status
                result = self.dal.preReserveAssignedBills(self.remote.consumers, through_date="2026-11-30")
                self.assertTrue(result["stopped_early"])
                self.assertEqual(result["failed"], 1)
                self.assertEqual(self.remote.count("/api/handheld/billing-references/reserve"), 1)
                self.assertEqual(self.remote.reservations, {})

    def test_single_reference_conflict_keeps_other_dates_prepared(self):
        self.remote.reserve_failure = 409
        result = self.dal.preReserveAssignedBills(self.remote.consumers, through_date="2026-11-30")
        self.assertFalse(result.get("stopped_early", False))
        self.assertEqual((result["ready"], result["failed"]), (8, 1))

    def test_health_shortcut_does_not_bypass_session_requirement(self):
        self.remote.set_authenticated_session(None)
        result = self.dal.preReserveAssignedBills(self.remote.consumers, through_date="2026-11-30")
        self.assertTrue(result["stopped_early"])
        self.assertEqual(self.remote.count("/api/handheld/billing-references/reserve"), 0)
        self.assertEqual(result["ready"], 0)

    def test_schedule_failure_discards_previous_download_snapshot(self):
        self.dal.loadAssignedConsumers(12, None, "2026-11-01", "2026-11-30", require_online=True)
        self.assertIsNotNone(self.dal.last_assignment_schedules)
        self.remote.schedule_failure = 503
        with self.assertRaises(BackendRequestError):
            self.dal.loadAssignedConsumers(12, None, "2026-11-01", "2026-11-30", require_online=True)
        self.assertIsNone(self.dal.last_assignment_schedules)

    def test_manual_sync_does_not_queue_another_pull_behind_automatic_download(self):
        view = self.view()
        view._assigned_dataset_refreshing = True
        with patch("src.qt_hybrid_app.threading.Thread") as worker:
            AppBridge.syncNow(view)
        worker.assert_not_called()
        view.alertRequested.emit.assert_called_once()
        self.assertEqual(self.remote.requests, [])

    def test_automatic_pull_does_not_queue_behind_manual_sync(self):
        view = self.view()
        view._operation_busy = True
        with patch("src.qt_hybrid_app.threading.Thread") as worker:
            AppBridge._start_assigned_consumer_dataset_refresh(view)
        worker.assert_not_called()

    def test_progress_updates_busy_message_but_cannot_reopen_finished_operation(self):
        view = self.view()
        view._operation_busy = True
        AppBridge._show_sync_progress(view, "Downloading offline records: 2/3")
        view._set_operation_busy.assert_called_once_with(True, "Downloading offline records: 2/3")
        view._set_operation_busy.reset_mock()
        view._operation_busy = False
        AppBridge._show_sync_progress(view, "Late progress")
        view._set_operation_busy.assert_not_called()

    def test_missing_offline_records_are_reported_as_incomplete_sync(self):
        view = self.view()
        view._last_pull_mirror = view._last_pull_count = 0
        view._refresh_local_assignment_views = Mock()
        view._reload_current_consumer_from_db = Mock()
        view._refresh_sync_snapshot = Mock()
        AppBridge._finish_sync_task(view, {
            "kind": "sync", "result": {},
            "context_pull": {"requested": 3, "refreshed": 2, "failed": 1},
        })
        title, message = view.alertRequested.emit.call_args.args
        self.assertEqual(title, "Sync Finished with Problems")
        self.assertIn("Offline records: 2/3", message)
        self.assertIn("Offline records not downloaded: 1", message)

    def test_global_context_failure_cancels_waiting_records_and_retains_cache(self):
        self.dal.local.cache_consumers(self.remote.consumers)
        many = [{"id": i} for i in range(1, 101)]
        with patch.object(self.remote, "get_consumer_context", side_effect=BackendRequestError(0, "DNS unavailable")) as fetch:
            result = self.dal.prefetchAssignedConsumerContexts(many)
        self.assertTrue(result["stopped_early"])
        self.assertEqual((result["requested"], result["failed"]), (100, 100))
        self.assertLess(fetch.call_count, 100)
        self.assertEqual(len(self.dal.local.load_cached_consumers()), 3)


if __name__ == "__main__":
    unittest.main()

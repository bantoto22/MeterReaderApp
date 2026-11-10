import gc
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import database
from src.handheld_sync import HandheldSyncDataAccess, SQLiteLocalSyncStore, SyncConfig
from src.qt_hybrid_app import AppBridge


class AssignmentBackend:
    def __init__(self):
        self.status = "Cancelled"
        self.filters = []
        self.uploads = []
        self._url = "https://device.example.test/api"

    def is_online(self):
        return True

    def load_reading_schedules(self, reader, date_from, date_to, status):
        self.filters.append(status)
        return [{
            "schedule_id": 538, "meter_reader_id": 2, "zone_name": "Zone 1",
            "start_date": "2026-10-20", "due_date": "2026-10-31",
            "billing_month": "October 2026", "status": self.status,
        }] if status == self.status else []

    def load_assigned_consumers(self, *args):
        return []

    def find_existing_reading(self, consumer_id, reading_date):
        return None

    def save_reading_bundle(self, payload):
        self.uploads.append(dict(payload))
        if self.status == "Cancelled" and payload["schedule_id"] == 538:
            raise RuntimeError(
                "HTTP 400 /api/handheld/reading-bundles: "
                "This concessionaire is not part of the selected reading assignment."
            )
        return {
            "meterreading": {"reading_status": "Recorded", "sync_status": "synced"},
            "bill": {"bill_id": 305, "sync_id": payload["bill_sync_id"],
                     "billing_reference": payload["billing_reference"]},
        }


class CancelledScheduleSyncTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = str(Path(directory.name) / "cancelled.db")
        db_patch = patch.object(database, "_db_path", return_value=path)
        db_patch.start()
        self.addCleanup(db_patch.stop)
        self.addCleanup(gc.collect)
        database.init_db()
        self.remote = AssignmentBackend()
        self.store = SQLiteLocalSyncStore(SyncConfig())
        self.store._db_path = path
        self.dal = HandheldSyncDataAccess(self.store, self.remote)
        schedule = {
            "schedule_id": 538, "meter_reader_id": 2, "zone_name": "Zone 1",
            "start_date": "2026-10-20", "due_date": "2026-10-31", "status": "In Progress",
        }
        database.replace_reading_schedules_from_sync([schedule], 2, "2026-08-01", "2026-10-31")
        self.store.cache_reading_schedules([schedule], 2, "2026-08-01", "2026-10-31")
        consumer = {"id": 81, "meter_no": "MTR-81", "name": "Test Consumer", "zone_name": "Zone 1",
                    "schedule_id": 538, "is_read": False}
        database.replace_consumers_from_sync([consumer])
        self.store.cache_consumers([consumer])
        draft = self.store.get_or_create_bill_reservation(81, "2026-10-24", schedule_id=538)
        self.store.save_reserved_reference(draft["bill_sync_id"], "SLR2026000305")
        self.payload = {
            "consumer_id": 81, "schedule_id": 538, "meter_reader_id": 2,
            "schedule_date": "2026-10-20", "reading_date": "2026-10-24",
            "present_reading": 10, "consumption": 5,
            "reading_id": draft["reading_sync_id"], "bill_sync_id": draft["bill_sync_id"],
            "bill_date": draft["bill_date"], "billing_reference": "SLR2026000305",
        }
        database.save_reading(81, 10, 5, reading_date="2026-10-24", schedule_id=538,
                              sync_reading_id=draft["reading_sync_id"])
        self.dal.queueMeterReading(dict(self.payload))

    def assert_saved_reading_unchanged(self):
        queued = self.dal.listPendingSyncReadings() + self.dal.listReviewReadings()
        self.assertEqual(len(queued), 1)
        for key in ("schedule_id", "reading_id", "bill_sync_id", "bill_date", "billing_reference"):
            self.assertEqual(queued[0]["payload"][key], self.payload[key])
        conn = database.get_connection()
        try:
            reading = conn.execute("SELECT * FROM readings WHERE sync_reading_id=?",
                                   (self.payload["reading_id"],)).fetchone()
            self.assertEqual(reading["present_reading"], 10)
            self.assertEqual(reading["schedule_id"], 538)
            self.assertEqual(reading["reading_status"], "valid")
        finally:
            conn.close()

    def test_sync_downloads_cancellation_and_hides_route_without_removing_saved_reading(self):
        self.assertEqual(database.get_assigned_routes(2)[0]["schedule_id"], 538)
        self.dal.loadAssignedConsumers(2, None, "2026-08-01", "2026-10-31")
        self.assertIn("Cancelled", self.remote.filters)
        self.assertEqual(database.get_assigned_routes(2), [])
        self.assertEqual(self.dal.listPendingSyncReadings(), [])
        self.assertEqual(len(self.dal.listReviewReadings()), 1)
        self.assert_saved_reading_unchanged()

    def test_ui_schedule_refresh_reuses_downloaded_cancellation(self):
        self.dal.loadAssignedConsumers(2, None, "2026-08-01", "2026-10-31", require_online=True)
        requested_statuses = list(self.remote.filters)
        bridge = SimpleNamespace(_sync_dal=self.dal, _meter_reader_account_id=2)
        self.assertEqual(AppBridge._mirror_assigned_schedules(bridge, "2026-08-01", "2026-10-31"), 1)
        self.assertEqual(self.remote.filters, requested_statuses)
        self.assertEqual(database.get_assigned_routes(2), [])
        self.assert_saved_reading_unchanged()

    def test_first_sync_detects_cancellation_even_when_cached_schedule_is_active(self):
        result = self.dal.syncPendingReadings()
        self.assertEqual((result["failed"], result["synced"], result["needs_review"]), (0, 0, 1))
        self.assertEqual(result["errors"], [])
        self.assertEqual(self.remote.uploads, [])
        diagnostic = next(row["message"] for row in self.dal.get_recent_audit_entries()
                          if row["status"] == "needs_review")
        for detail in ("Cancelled schedule", "Schedule ID: 538", "Consumer ID: 81",
                       "Billing reference: SLR2026000305"):
            self.assertIn(detail, diagnostic)
        self.assertNotIn("Unexpected sync error", diagnostic)
        self.assert_saved_reading_unchanged()
        self.dal.loadAssignedConsumers(2, None, "2026-08-01", "2026-10-31")
        uploads_before_retry = len(self.remote.uploads)
        retry = self.dal.syncPendingReadings()
        self.assertEqual((retry["failed"], retry["needs_review"]), (0, 1))
        self.assertEqual(retry["errors"], [])
        self.assertEqual(len(self.remote.uploads), uploads_before_retry)
        snapshot = self.dal.get_sync_snapshot()
        self.assertFalse(snapshot["has_failed"])
        self.assertEqual((snapshot["pending_count"], snapshot["review_count"]), (0, 1))
        self.remote.status = "In Progress"
        self.dal.loadAssignedConsumers(2, None, "2026-08-01", "2026-10-31")
        self.assertEqual(self.dal.listReviewReadings(), [])
        self.assertEqual(self.dal.syncPendingReadings()["synced"], 1)
        for upload in self.remote.uploads:
            for key in ("schedule_id", "reading_id", "bill_sync_id", "bill_date", "billing_reference"):
                self.assertEqual(upload[key], self.payload[key])

    def test_cancellation_between_check_and_upload_is_held_without_sync_failure(self):
        self.remote.status = "In Progress"
        draft = self.store.get_or_create_bill_reservation(83, "2026-10-24", schedule_id=538)
        self.store.save_reserved_reference(draft["bill_sync_id"], "SLR2026000307")
        self.dal.queueMeterReading({
            **self.payload, "consumer_id": 83, "reading_id": draft["reading_sync_id"],
            "bill_sync_id": draft["bill_sync_id"], "billing_reference": "SLR2026000307",
        })
        self.add_normal_reading()
        original_upload = self.remote.save_reading_bundle

        def cancel_during_upload(payload):
            if payload["consumer_id"] == 81:
                self.remote.status = "Cancelled"
                raise RuntimeError(
                    "HTTP 400 /api/handheld/reading-bundles: "
                    "This concessionaire is not part of the selected reading assignment."
                )
            return original_upload(payload)

        with patch.object(self.remote, "save_reading_bundle", side_effect=cancel_during_upload) as upload:
            result = self.dal.syncPendingReadings()
            repeated = self.dal.syncPendingReadings()
        self.assertEqual([call.args[0]["consumer_id"] for call in upload.call_args_list], [81, 82])
        self.assertEqual((result["synced"], result["failed"], result["needs_review"]), (1, 0, 2))
        self.assertEqual(result["errors"], [])
        self.assertEqual(repeated["failed"], 0)
        held = {row["payload"]["consumer_id"]: row["payload"] for row in self.dal.listReviewReadings()}
        self.assertEqual(held[81]["billing_reference"], "SLR2026000305")
        self.assertEqual(held[83]["billing_reference"], "SLR2026000307")

    def test_online_save_checks_cancellation_before_uploading(self):
        draft = self.store.get_or_create_bill_reservation(83, "2026-10-24", schedule_id=538)
        self.store.save_reserved_reference(draft["bill_sync_id"], "SLR2026000307")
        result = self.dal.saveMeterReading({
            **self.payload, "consumer_id": 83, "reading_id": draft["reading_sync_id"],
            "bill_sync_id": draft["bill_sync_id"], "billing_reference": "SLR2026000307",
        })
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(self.remote.uploads, [])
        self.assertEqual(self.dal.listPendingSyncReadings(), [])
        held = {row["payload"]["consumer_id"]: row["payload"] for row in self.dal.listReviewReadings()}
        self.assertEqual(held[81]["billing_reference"], "SLR2026000305")
        self.assertEqual(held[83]["billing_reference"], "SLR2026000307")

    def test_assignment_rejection_without_confirmed_cancellation_remains_a_failure(self):
        self.remote.status = "In Progress"
        error = RuntimeError("HTTP 400: This concessionaire is not part of the selected reading assignment.")
        with patch.object(self.remote, "save_reading_bundle", side_effect=error):
            result = self.dal.syncPendingReadings()
        self.assertEqual((result["failed"], result["needs_review"]), (1, 0))
        self.assertIn("schedule assignment", result["errors"][0])
        self.assertEqual(len(self.dal.listPendingSyncReadings()), 1)
        self.assert_saved_reading_unchanged()

    def test_authentication_rejection_during_cancellation_check_does_not_upload(self):
        with patch.object(self.remote, "load_reading_schedules", side_effect=RuntimeError("HTTP 403: Forbidden")):
            with self.assertRaises(PermissionError):
                self.dal.syncPendingReadings()
        self.assertEqual(self.remote.uploads, [])
        self.assertEqual(len(self.dal.listPendingSyncReadings()), 1)
        self.assertEqual(self.dal.listReviewReadings(), [])
        self.assert_saved_reading_unchanged()

    def add_normal_reading(self):
        schedule = {
            "schedule_id": 549, "meter_reader_id": 2, "zone_name": "Zone 2",
            "start_date": "2026-10-24", "due_date": "2026-10-31", "status": "Scheduled",
        }
        database.replace_reading_schedules_from_sync([schedule], 2, "2026-10-01", "2026-10-31")
        consumer = {"id": 82, "meter_no": "MTR-82", "name": "Other Consumer", "zone_name": "Zone 2",
                    "schedule_id": 549, "is_read": False}
        database.replace_consumers_from_sync([consumer])
        draft = self.store.get_or_create_bill_reservation(82, "2026-10-24", schedule_id=549)
        self.store.save_reserved_reference(draft["bill_sync_id"], "SLR2026000306")
        database.save_reading(82, 20, 5, reading_date="2026-10-24", schedule_id=549,
                              sync_reading_id=draft["reading_sync_id"])
        return self.dal.queueMeterReading({
            **self.payload, "consumer_id": 82, "schedule_id": 549, "present_reading": 20,
            "schedule_date": "2026-10-24", "reading_id": draft["reading_sync_id"],
            "bill_sync_id": draft["bill_sync_id"], "billing_reference": "SLR2026000306",
        })

    def test_cancelled_reading_does_not_fail_or_resend_when_other_readings_sync(self):
        self.dal.loadAssignedConsumers(2, None, "2026-08-01", "2026-10-31")
        self.add_normal_reading()
        result = self.dal.syncPendingReadings()
        self.assertEqual((result["synced"], result["failed"], result["needs_review"]), (1, 0, 1))
        self.assertEqual(result["errors"], [])
        self.assertEqual([row["consumer_id"] for row in self.remote.uploads], [82])
        self.assertEqual(self.remote.uploads[0]["billing_reference"], "SLR2026000306")
        for _ in range(2):
            repeated = self.dal.syncPendingReadings()
            self.assertEqual((repeated["synced"], repeated["failed"], repeated["needs_review"]), (0, 0, 1))
        self.assertEqual(len(self.remote.uploads), 1)
        self.assert_saved_reading_unchanged()

    def test_existing_failed_reading_becomes_needs_review_after_restart_without_changing_payload(self):
        queued = self.dal.listPendingSyncReadings()[0]
        self.store.mark_target_failed(queued["id"], "backend", "Assignment rejected")
        conn = database.get_connection()
        try:
            before = conn.execute("SELECT payload FROM sync_queue_meter_readings WHERE id=?", (queued["id"],)).fetchone()[0]
            conn.execute("UPDATE reading_schedule SET status='Cancelled' WHERE schedule_id=538")
            conn.commit()
        finally:
            conn.close()
        reopened = SQLiteLocalSyncStore(SyncConfig())
        reopened._db_path = self.store._db_path
        self.dal = HandheldSyncDataAccess(reopened, self.remote)
        review = self.dal.listReviewReadings()
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["status"], "needs_review")
        conn = database.get_connection()
        try:
            after = conn.execute("SELECT payload FROM sync_queue_meter_readings WHERE id=?", (queued["id"],)).fetchone()[0]
            self.assertEqual(before, after)
        finally:
            conn.close()
        self.assertFalse(self.dal.get_sync_snapshot()["has_failed"])
        self.assertEqual(self.dal.syncPendingReadings()["failed"], 0)
        self.assertEqual(self.remote.uploads, [])
        self.assert_saved_reading_unchanged()

    def test_needs_review_survives_assignment_refresh_and_labels_the_saved_reading(self):
        self.dal.loadAssignedConsumers(2, None, "2026-08-01", "2026-10-31")
        database.replace_consumers_from_sync([{
            "id": 81, "meter_no": "MTR-81", "name": "Test Consumer", "zone_name": "Zone 1",
            "schedule_id": 538, "is_read": False, "reading_sync_status": "pending",
        }])
        row = database.get_zone_consumers_with_status("Zone 1", meter_reader_id=2, schedule_id=538)[0]
        self.assertTrue(row["is_read"])
        self.assertEqual(row["reading_sync_status"], "needs_review")
        self.assertEqual(row["reading_sync_label"], "Needs review")
        self.assert_saved_reading_unchanged()

    def test_needs_review_does_not_hide_a_real_failure_from_another_reading(self):
        self.dal.loadAssignedConsumers(2, None, "2026-08-01", "2026-10-31")
        self.add_normal_reading()
        with patch.object(self.remote, "save_reading_bundle", side_effect=RuntimeError("Request timed out")):
            result = self.dal.syncPendingReadings()
        self.assertEqual((result["failed"], result["needs_review"]), (1, 1))
        self.assertIn("timed out", result["errors"][0])
        self.assertTrue(self.dal.get_sync_snapshot()["has_failed"])
        self.assertEqual(self.dal.listPendingSyncReadings()[0]["payload"]["consumer_id"], 82)

    def test_review_does_not_resume_for_a_reassigned_reader(self):
        self.dal.loadAssignedConsumers(2, None, "2026-08-01", "2026-10-31")
        changed = {"schedule_id": 538, "meter_reader_id": 3, "zone_name": "Zone 1",
                   "start_date": "2026-10-20", "due_date": "2026-10-31", "status": "Scheduled"}
        self.store.cache_reading_schedules([changed], 3, "2026-08-01", "2026-10-31")
        self.dal.reconcileScheduleReadings([changed])
        self.assertEqual(self.dal.listPendingSyncReadings(), [])
        self.assert_saved_reading_unchanged()

    def snapshot_view(self):
        return SimpleNamespace(
            _sync_dal=self.dal, _backend_status="Online", _backend_endpoint=self.remote._url,
            _auto_sync_enabled=True, _emit_sync_state=Mock(),
            syncLogsChanged=SimpleNamespace(emit=Mock()), backendLogsChanged=SimpleNamespace(emit=Mock()),
        )

    def test_review_count_is_visible_while_overall_sync_status_stays_online(self):
        self.dal.loadAssignedConsumers(2, None, "2026-08-01", "2026-10-31")
        view = self.snapshot_view()
        AppBridge._refresh_sync_snapshot(view, self.dal.get_sync_snapshot())
        self.assertEqual(view._sync_status, "Online")
        self.assertEqual((view._sync_pending_count, view._sync_review_count), (0, 1))
        self.assertIn("SLR2026000305", view._sync_review_summary)
        self.assertIn("Needs review: 1", view._sync_logs)

    def test_sync_summary_completes_with_separate_review_count(self):
        self.dal.loadAssignedConsumers(2, None, "2026-08-01", "2026-10-31")
        view = self.snapshot_view()
        view._last_pull_mirror = 0
        view._last_pull_count = 0
        view._set_operation_busy = Mock()
        view._refresh_local_assignment_views = Mock()
        view._reload_current_consumer_from_db = Mock()
        view._refresh_sync_snapshot = Mock()
        view.alertRequested = SimpleNamespace(emit=Mock())
        AppBridge._finish_sync_task(view, {"kind": "sync", "result": self.dal.syncPendingReadings()})
        title, message = view.alertRequested.emit.call_args.args
        self.assertEqual(title, "Sync Complete")
        self.assertIn("Failed: 0", message)
        self.assertIn("Needs review: 1", message)
        self.assertNotIn("First problem", message)


if __name__ == "__main__":
    unittest.main()

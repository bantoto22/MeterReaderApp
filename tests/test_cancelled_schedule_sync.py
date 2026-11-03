import gc
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
            "start_date": "2026-08-27", "due_date": "2026-09-01",
            "billing_month": "August 2026", "status": self.status,
        }] if status == self.status else []

    def load_assigned_consumers(self, *args):
        return []

    def find_existing_reading(self, consumer_id, reading_date):
        return None

    def save_reading_bundle(self, payload):
        self.uploads.append(dict(payload))
        if self.status == "Cancelled":
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
            "start_date": "2026-08-27", "due_date": "2026-09-01", "status": "In Progress",
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
            "schedule_date": "2026-08-27", "reading_date": "2026-10-24",
            "present_reading": 10, "consumption": 5,
            "reading_id": draft["reading_sync_id"], "bill_sync_id": draft["bill_sync_id"],
            "bill_date": draft["bill_date"], "billing_reference": "SLR2026000305",
        }
        database.save_reading(81, 10, 5, reading_date="2026-10-24", schedule_id=538,
                              sync_reading_id=draft["reading_sync_id"])
        self.dal.queueMeterReading(dict(self.payload))

    def assert_saved_reading_unchanged(self):
        queued = self.dal.listPendingSyncReadings()
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
        self.assert_saved_reading_unchanged()

    def test_ui_schedule_refresh_also_downloads_cancellation(self):
        bridge = SimpleNamespace(_sync_dal=self.dal, _meter_reader_account_id=2)
        self.assertEqual(AppBridge._mirror_assigned_schedules(bridge, "2026-08-01", "2026-10-31"), 1)
        self.assertEqual(database.get_assigned_routes(2), [])
        self.assert_saved_reading_unchanged()

    def test_rejection_explains_assignment_and_keeps_reference_for_later_authorized_resolution(self):
        result = self.dal.syncPendingReadings()
        self.assertEqual((result["failed"], result["synced"]), (1, 0))
        diagnostic = result["errors"][0]
        for detail in ("schedule assignment", "cancellation status", "Schedule ID: 538",
                       "Meter reader ID: 2", "Consumer ID: 81", "Billing reference: SLR2026000305"):
            self.assertIn(detail, diagnostic)
        self.assertNotIn("Unexpected sync error", diagnostic)
        self.assert_saved_reading_unchanged()
        self.remote.status = "In Progress"
        self.assertEqual(self.dal.syncPendingReadings()["synced"], 1)
        for upload in self.remote.uploads:
            for key in ("schedule_id", "reading_id", "bill_sync_id", "bill_date", "billing_reference"):
                self.assertEqual(upload[key], self.payload[key])


if __name__ == "__main__":
    unittest.main()

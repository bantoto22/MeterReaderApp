import gc
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from src import database
from src.handheld_sync import HandheldSyncDataAccess, SQLiteLocalSyncStore, SyncConfig


class Remote:
    def __init__(self):
        self.online = True
        self.lose_response = False
        self.saved = []
        self.existing = None
        self.statuses = {"reading_status": "Recorded", "sync_status": "synced"}

    def is_online(self):
        return self.online

    def find_existing_reading(self, consumer_id, reading_date):
        return self.existing

    def save_reading_bundle(self, payload):
        self.saved.append(dict(payload))
        self.existing = {"id": 700, "sync_id": payload["reading_id"], "updated_at": "2100-01-01"}
        if self.lose_response:
            raise RuntimeError("Connection closed after the server saved the bundle")
        return {
            "meterreading": {**self.existing, **self.statuses},
            "bill": {"bill_id": 800, "sync_id": payload["bill_sync_id"]},
        }


class ReadingSyncStatusTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name) / "meter.db")
        db_patch = patch.object(database, "_db_path", return_value=self.path)
        db_patch.start()
        self.addCleanup(db_patch.stop)
        self.addCleanup(gc.collect)
        database.init_db()
        self.today = date.today().isoformat()
        due = (date.today() + timedelta(days=7)).isoformat()
        database.replace_reading_schedules_from_sync([{
            "schedule_id": 101, "start_date": self.today, "due_date": due,
            "zone_name": "Zone 1", "meter_reader_id": 12, "status": "Scheduled",
        }], 12, self.today, due)
        self.consumer = {
            "id": 1, "meter_no": "MTR-1", "acct_no": "ACCT-1", "name": "Consumer 1",
            "zone_name": "Zone 1", "schedule_id": 101, "is_read": False,
            "reading_status": "pending", "reading_sync_status": "pending",
        }
        database.replace_consumers_from_sync([self.consumer])
        self.store = self._store()
        self.remote = Remote()
        self.dal = HandheldSyncDataAccess(self.store, self.remote)
        draft = self.store.get_or_create_bill_reservation(1, self.today, schedule_id=101)
        self.payload = {
            "consumer_id": 1, "reading_id": draft["reading_sync_id"],
            "operation_id": "operation-1", "reading_date": self.today,
            "bill_sync_id": draft["bill_sync_id"], "bill_date": self.today,
            "billing_reference": "SLR2026000125", "schedule_id": 101,
            "present_reading": 10, "consumption": 10,
            "reading_status": "valid", "reading_sync_status": "pending",
        }
        self.local_id = database.save_reading(
            1, 10, 10, reading_date=self.today, schedule_id=101,
            sync_reading_id=self.payload["reading_id"],
        )

    def _store(self):
        store = SQLiteLocalSyncStore(SyncConfig())
        store._db_path = self.path
        store.ensure_schema()
        return store

    def _display(self, **kwargs):
        return database.get_zone_consumers_with_status("Zone 1", **kwargs)[0]

    def _assert_confirmed(self, status="Recorded", sync="synced"):
        conn = database.get_connection()
        try:
            rows = conn.execute("SELECT * FROM readings").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], self.local_id)
            self.assertEqual(rows[0]["sync_reading_id"], self.payload["reading_id"])
            self.assertEqual(rows[0]["reading_status"], status)
            self.assertEqual(rows[0]["reading_sync_status"], sync)
            queue = conn.execute("SELECT * FROM sync_queue_meter_readings").fetchall()
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["backend_status"], "synced")
            original = json.loads(queue[0]["payload"])
            self.assertEqual(original["reading_id"], self.payload["reading_id"])
            self.assertEqual(original["bill_sync_id"], self.payload["bill_sync_id"])
            self.assertEqual(json.loads(queue[0]["server_payload"])["meterreading"]["reading_status"], status)
        finally:
            conn.close()
        display = self._display(meter_reader_id=12, schedule_id=101)
        self.assertEqual(display["reading_status_label"], status)
        self.assertEqual(display["reading_sync_status"], sync)

    def test_immediate_upload_uses_server_statuses_and_retains_local_ids(self):
        result = self.dal.saveMeterReading(self.payload)
        self.assertEqual(result["reading"]["reading_status"], "Recorded")
        self.assertEqual(result["reading"]["reading_sync_status"], "synced")
        self._assert_confirmed()
        self.assertEqual(self._display()["reading_status_label"], "Recorded")
        self.assertEqual(self._display()["reading_sync_label"], "Synced")

    def test_offline_reading_shows_waiting_then_server_status_after_upload(self):
        self.remote.online = False
        self.dal.queueMeterReading(self.payload)
        waiting = self._display(meter_reader_id=12, schedule_id=101)
        self.assertEqual(waiting["reading_status_label"], "Saved")
        self.assertEqual(waiting["reading_sync_label"], "Waiting to sync")
        self.remote.online = True
        self.assertEqual(self.dal.syncPendingReadings()["synced"], 1)
        self._assert_confirmed()

    def test_retry_after_lost_response_and_restart_reuses_reading_and_bill(self):
        self.remote.lose_response = True
        self.dal.saveMeterReading(self.payload)
        failed = self._display(meter_reader_id=12, schedule_id=101)
        self.assertEqual(failed["reading_sync_label"], "Sync failed")
        self.remote.lose_response = False
        restarted = HandheldSyncDataAccess(self._store(), self.remote)
        result = restarted.syncPendingReadings()
        self.assertEqual((result["synced"], result["conflicts"]), (1, 0))
        self.assertEqual(len(self.remote.saved), 2)
        for field in ("reading_id", "bill_sync_id", "operation_id", "billing_reference"):
            self.assertEqual(self.remote.saved[0][field], self.remote.saved[1][field])
        self._assert_confirmed()
        self.assertEqual(restarted.syncPendingReadings()["synced"], 0)
        self.assertEqual(len(self.remote.saved), 2)

    def test_server_sync_status_is_separate_from_reading_status(self):
        self.remote.statuses = {"reading_status": "For review", "sync_status": "pending"}
        self.dal.saveMeterReading(self.payload)
        self._assert_confirmed("For review", "pending")
        self.assertEqual(self._display(meter_reader_id=12, schedule_id=101)["reading_sync_label"], "Waiting to sync")
        database.replace_consumers_from_sync([self.consumer])
        self._assert_confirmed("For review", "pending")

    def test_consumer_refresh_keeps_server_reading_status(self):
        self.dal.saveMeterReading(self.payload)
        database.replace_consumers_from_sync([{
            **self.consumer, "is_read": True, "reading_status": "Recorded",
            "reading_sync_status": "synced",
        }])
        self._assert_confirmed()

    def test_missing_response_status_preserves_existing_reading_status(self):
        database.update_reading_sync_state(self.payload["reading_id"], "pending", "For review")
        self.remote.statuses = {}
        self.dal.saveMeterReading(self.payload)
        display = self._display(meter_reader_id=12, schedule_id=101)
        self.assertEqual(display["reading_status"], "For review")
        self.assertEqual(display["reading_sync_status"], "synced")

    def test_rejected_server_status_reopens_assignment_without_losing_status(self):
        self.remote.statuses = {"reading_status": "Rejected", "sync_status": "synced"}
        self.dal.saveMeterReading(self.payload)
        self._assert_confirmed("Rejected")
        self.assertFalse(self._display(meter_reader_id=12, schedule_id=101)["is_read"])


if __name__ == "__main__":
    unittest.main()

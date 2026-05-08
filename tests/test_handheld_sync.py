import unittest
from datetime import datetime, timezone

from src.handheld_sync import HandheldSyncDataAccess


class FakeLocalStore:
    def __init__(self):
        self.queue = []
        self.audit = []
        self.cached = []
        self._id = 1

    def ensure_schema(self):
        return

    def cache_consumers(self, consumers):
        self.cached = list(consumers)

    def load_cached_consumers(self, zone_name=None):
        if not zone_name:
            return list(self.cached)
        return [c for c in self.cached if c.get("zone_name") == zone_name]

    def enqueue_operation(self, operation, payload):
        row = {
            "id": self._id,
            "operation": operation,
            "operation_id": payload["operation_id"],
            "reading_id": payload["reading_id"],
            "consumer_id": payload["consumer_id"],
            "reading_date": payload["reading_date"],
            "payload": dict(payload),
            "status": "pending",
            "retries": 0,
        }
        self._id += 1
        self.queue.append(row)
        return row

    def list_pending(self):
        return [q for q in self.queue if q["status"] in ("pending", "failed")]

    def mark_synced(self, queue_id):
        for q in self.queue:
            if q["id"] == queue_id:
                q["status"] = "synced"

    def mark_failed(self, queue_id, reason):
        for q in self.queue:
            if q["id"] == queue_id:
                q["status"] = "failed"
                q["last_error"] = reason
                q["retries"] += 1

    def mark_conflict(self, queue_id, reason, server_payload=None):
        for q in self.queue:
            if q["id"] == queue_id:
                q["status"] = "conflict"
                q["conflict_reason"] = reason
                q["server_payload"] = server_payload

    def log_audit(self, queue_id, status, message, payload=None):
        self.audit.append({"queue_id": queue_id, "status": status, "message": message, "payload": payload})


class FakeRemoteStore:
    def __init__(self):
        self.online = False
        self.remote_rows = {}
        self.fail_writes = False

    def is_online(self):
        return self.online

    def load_assigned_consumers(self, zone_name=None):
        return []

    def _key(self, consumer_id, reading_date):
        return f"{consumer_id}:{reading_date}"

    def find_existing_reading(self, consumer_id, reading_date):
        return self.remote_rows.get(self._key(consumer_id, reading_date))

    def upsert_meter_reading(self, payload):
        if self.fail_writes:
            raise RuntimeError("remote write error")
        key = self._key(payload["consumer_id"], payload["reading_date"])
        self.remote_rows[key] = dict(payload)
        return dict(payload)


class HandheldSyncTests(unittest.TestCase):
    def setUp(self):
        self.local = FakeLocalStore()
        self.remote = FakeRemoteStore()
        self.dal = HandheldSyncDataAccess(self.local, self.remote)

    def test_offline_save_queues(self):
        self.remote.online = False
        result = self.dal.saveMeterReading({"consumer_id": 1, "present_reading": 100, "reading_date": "2026-05-08"})
        self.assertEqual(result["status"], "queued")
        self.assertEqual(len(self.local.list_pending()), 1)

    def test_reconnect_sync_flushes_queue(self):
        self.remote.online = False
        self.dal.saveMeterReading({"consumer_id": 2, "present_reading": 120, "reading_date": "2026-05-08"})
        self.remote.online = True
        result = self.dal.syncPendingReadings()
        self.assertEqual(result["synced"], 1)
        self.assertEqual(len(self.local.list_pending()), 0)

    def test_duplicate_prevention_by_reading_id(self):
        self.remote.online = True
        payload = {
            "reading_id": "fixed-id",
            "consumer_id": 3,
            "present_reading": 150,
            "reading_date": "2026-05-08",
        }
        self.dal.saveMeterReading(payload)
        self.dal.updateMeterReading(payload)
        self.assertEqual(len(self.remote.remote_rows), 1)

    def test_conflict_marks_row(self):
        self.remote.online = False
        local_ts = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc).isoformat()
        self.dal.saveMeterReading(
            {
                "consumer_id": 4,
                "present_reading": 180,
                "reading_date": "2026-05-08",
                "updated_at": local_ts,
            }
        )
        key = self.remote._key(4, "2026-05-08")
        self.remote.remote_rows[key] = {
            "consumer_id": 4,
            "reading_date": "2026-05-08",
            "updated_at": datetime(2026, 5, 8, 11, 0, tzinfo=timezone.utc).isoformat(),
            "present_reading": 200,
        }
        self.remote.online = True
        result = self.dal.syncPendingReadings()
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(self.local.queue[0]["status"], "conflict")


if __name__ == "__main__":
    unittest.main()

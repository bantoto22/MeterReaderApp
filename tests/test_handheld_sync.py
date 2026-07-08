import unittest
from datetime import datetime, timezone

from src.handheld_sync import HandheldSyncDataAccess, _build_bill_payload
from src.receipt import build_receipt_text


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

    @staticmethod
    def _combined_status(supabase_status, main_pg_status):
        states = {str(supabase_status or "").lower(), str(main_pg_status or "").lower()}
        if states & {"pending", "failed"}:
            return "failed" if "failed" in states else "pending"
        if "conflict" in states:
            return "conflict"
        return "synced"

    def _refresh_status(self, row):
        row["status"] = self._combined_status(row.get("supabase_status"), row.get("main_pg_status"))

    def enqueue_operation(self, operation, payload, *, supabase_status="pending", main_pg_status="pending"):
        row = {
            "id": self._id,
            "operation": operation,
            "operation_id": payload["operation_id"],
            "reading_id": payload["reading_id"],
            "consumer_id": payload["consumer_id"],
            "reading_date": payload["reading_date"],
            "payload": dict(payload),
            "status": self._combined_status(supabase_status, main_pg_status),
            "supabase_status": supabase_status,
            "main_pg_status": main_pg_status,
            "retries": 0,
        }
        self._id += 1
        self.queue.append(row)
        return row

    def list_pending(self, target=None):
        if target == "supabase":
            return [q for q in self.queue if q["supabase_status"] in ("pending", "failed")]
        if target == "main_pg":
            return [q for q in self.queue if q["main_pg_status"] in ("pending", "failed")]
        return [
            q for q in self.queue
            if q["supabase_status"] in ("pending", "failed") or q["main_pg_status"] in ("pending", "failed")
        ]

    def mark_target_synced(self, queue_id, target):
        for q in self.queue:
            if q["id"] == queue_id:
                q[f"{target}_status"] = "synced"
                self._refresh_status(q)

    def mark_target_failed(self, queue_id, target, reason):
        for q in self.queue:
            if q["id"] == queue_id:
                q[f"{target}_status"] = "failed"
                q["last_error"] = reason
                q["retries"] += 1
                self._refresh_status(q)

    def mark_conflict(self, queue_id, reason, server_payload=None, *, target=None):
        for q in self.queue:
            if q["id"] == queue_id:
                q[f"{target or 'supabase'}_status"] = "conflict"
                q["conflict_reason"] = reason
                q["server_payload"] = server_payload
                self._refresh_status(q)

    def log_audit(self, queue_id, status, message, payload=None):
        self.audit.append({"queue_id": queue_id, "status": status, "message": message, "payload": payload})


class FakeRemoteStore:
    def __init__(self):
        self.online = False
        self.remote_rows = {}
        self.fail_writes = False
        self.fail_reads = False
        self.assigned_consumers = []
        self.context_by_consumer = {}

    def is_online(self):
        return self.online

    def load_assigned_consumers(self, zone_name=None):
        return list(self.assigned_consumers)

    def _key(self, consumer_id, reading_date):
        return f"{consumer_id}:{reading_date}"

    def find_existing_reading(self, consumer_id, reading_date):
        if not self.online:
            raise RuntimeError("remote offline")
        if self.fail_reads:
            raise RuntimeError("remote read error")
        return self.remote_rows.get(self._key(consumer_id, reading_date))

    def upsert_meter_reading(self, payload):
        if not self.online:
            raise RuntimeError("remote offline")
        if self.fail_writes:
            raise RuntimeError("remote write error")
        key = self._key(payload["consumer_id"], payload["reading_date"])
        self.remote_rows[key] = dict(payload)
        return dict(payload)

    def get_consumer_context(self, consumer_id):
        return dict(self.context_by_consumer.get(consumer_id, {}))


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

    def test_manual_sync_sends_pending_rows_to_main_pg(self):
        class FakeMainPgStore(FakeRemoteStore):
            pass

        main_pg = FakeMainPgStore()
        main_pg.online = True
        self.remote.online = True
        self.dal = HandheldSyncDataAccess(self.local, self.remote, main_pg_client=main_pg)

        self.dal.saveMeterReading({"consumer_id": 5, "present_reading": 99, "reading_date": "2026-05-08"})

        result = self.dal.syncPendingReadings(include_main_pg=True)

        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(self.local.list_pending()), 0)
        self.assertEqual(len(main_pg.remote_rows), 1)
        self.assertEqual(len(self.remote.remote_rows), 1)

    def test_load_assigned_consumers_overlays_rates_from_main_pg(self):
        class FakeMainPgStore(FakeRemoteStore):
            def load_waterrates_by_classification(self):
                return {
                    1: {
                        "classification_id": 1,
                        "rate_id": 7,
                        "minimum_cubic": 10,
                        "minimum_rate": 150.0,
                        "excess_rate_per_cubic": 15.0,
                    }
                }

        main_pg = FakeMainPgStore()
        self.remote.online = True
        self.remote.assigned_consumers = [
            {
                "id": 8,
                "meter_no": "09-23-2233",
                "acct_no": "04-11-123",
                "name": "Charles Ivan Ornales De Vera",
                "classification_id": 1,
                "classification_name": "Residential",
                "minimum_cubic": 0,
                "minimum_rate": 50.0,
                "excess_rate_per_cubic": 10.0,
            }
        ]
        self.dal = HandheldSyncDataAccess(self.local, self.remote, main_pg_client=main_pg)

        rows = self.dal.loadAssignedConsumers()

        self.assertEqual(rows[0]["minimum_cubic"], 10)
        self.assertEqual(rows[0]["minimum_rate"], 150.0)
        self.assertEqual(rows[0]["excess_rate_per_cubic"], 15.0)

    def test_save_reading_overlays_rates_from_main_pg(self):
        class FakeMainPgStore(FakeRemoteStore):
            pass

        main_pg = FakeMainPgStore()
        main_pg.context_by_consumer = {
            8: {
                "consumer_id": 8,
                "minimum_cubic": 10,
                "minimum_rate": 150.0,
                "excess_rate_per_cubic": 15.0,
            }
        }
        self.remote.online = True
        self.dal = HandheldSyncDataAccess(self.local, self.remote, main_pg_client=main_pg)

        self.dal.saveMeterReading({"consumer_id": 8, "present_reading": 3, "reading_date": "2026-05-08"})

        saved = next(iter(self.remote.remote_rows.values()))
        self.assertEqual(saved["minimum_cubic"], 10)
        self.assertEqual(saved["minimum_rate"], 150.0)
        self.assertEqual(saved["excess_rate_per_cubic"], 15.0)

    def test_save_reading_skips_main_pg_until_manual_sync(self):
        class FakeMainPgStore(FakeRemoteStore):
            def save_reading_bundle(self, payload):
                return {"meterreading": self.upsert_meter_reading(payload)}

        main_pg = FakeMainPgStore()
        main_pg.online = True
        self.remote.online = True
        self.dal = HandheldSyncDataAccess(self.local, self.remote, main_pg_client=main_pg)

        result = self.dal.saveMeterReading({"consumer_id": 9, "present_reading": 12, "reading_date": "2026-05-08"})

        self.assertEqual(result["status"], "synced")
        self.assertEqual(list(result["remote"].keys()), ["Supabase"])
        self.assertEqual(len(main_pg.remote_rows), 0)
        self.assertEqual(len(self.remote.remote_rows), 1)
        self.assertEqual(len(self.local.list_pending("main_pg")), 1)

    def test_offline_supabase_does_not_auto_sync_to_main_pg(self):
        class FakeMainPgStore(FakeRemoteStore):
            def save_reading_bundle(self, payload):
                return {"meterreading": self.upsert_meter_reading(payload)}

        main_pg = FakeMainPgStore()
        main_pg.online = True
        self.remote.online = False
        self.remote.fail_writes = True
        self.dal = HandheldSyncDataAccess(self.local, self.remote, main_pg_client=main_pg)

        result = self.dal.saveMeterReading({"consumer_id": 10, "present_reading": 15, "reading_date": "2026-05-08"})

        self.assertEqual(result["status"], "queued")
        self.assertEqual(len(main_pg.remote_rows), 0)
        self.assertEqual(len(self.local.list_pending("supabase")), 1)

    def test_background_sync_leaves_main_pg_pending_until_manual(self):
        class FakeMainPgStore(FakeRemoteStore):
            def save_reading_bundle(self, payload):
                return {"meterreading": self.upsert_meter_reading(payload)}

        main_pg = FakeMainPgStore()
        main_pg.online = True
        self.remote.online = False
        self.dal = HandheldSyncDataAccess(self.local, self.remote, main_pg_client=main_pg)

        self.dal.saveMeterReading({"consumer_id": 11, "present_reading": 77, "reading_date": "2026-05-08"})
        self.remote.online = True

        result = self.dal.syncPendingReadings()

        self.assertEqual(result["synced"], 1)
        self.assertEqual(len(self.local.list_pending("supabase")), 0)
        self.assertEqual(len(self.local.list_pending("main_pg")), 1)
        self.assertEqual(len(main_pg.remote_rows), 0)

    def test_supabase_pending_helper_ignores_manual_main_pg_pending(self):
        class FakeMainPgStore(FakeRemoteStore):
            pass

        main_pg = FakeMainPgStore()
        main_pg.online = False
        self.remote.online = True
        self.dal = HandheldSyncDataAccess(self.local, self.remote, main_pg_client=main_pg)

        self.dal.saveMeterReading({"consumer_id": 12, "present_reading": 88, "reading_date": "2026-05-08"})

        self.assertEqual(len(self.dal.listPendingSupabaseReadings()), 0)
        self.assertEqual(len(self.dal.listPendingSyncReadings()), 1)
        self.assertEqual(self.local.queue[0]["supabase_status"], "synced")
        self.assertEqual(self.local.queue[0]["main_pg_status"], "pending")

    def test_bill_payload_defaults_after_due_penalty_to_ten_percent(self):
        payload = _build_bill_payload(
            {
                "reading_id": "7f00dbb6-656d-43b4-b4db-2bb206af9d21",
                "consumer_id": 42,
                "present_reading": 10,
                "previous_reading": 0,
                "consumption": 10,
                "reading_date": "2026-07-08",
            },
            {
                "minimum_cubic": 10,
                "minimum_rate": 100,
                "excess_rate_per_cubic": 15,
                "due_days": 15,
                "late_fee": None,
            },
            99,
        )

        self.assertEqual(payload["amount_due"], 100.0)
        self.assertEqual(payload["penalty"], 10.0)
        self.assertEqual(payload["total_after_due_date"], 110.0)

    def test_receipt_shows_projected_after_due_penalty_without_existing_record(self):
        text = build_receipt_text(
            {
                "id": 42,
                "acct_no": "09-99-0000",
                "name": "Test Consumer",
                "zone_name": "Zone 1",
                "classification_id": 1,
                "classification_name": "Residential",
                "meter_no": "MTR-TEST",
                "minimum_cubic": 10,
                "minimum_rate": 100,
                "excess_rate_per_cubic": 15,
                "due_days": 15,
                "amount_due": 100,
                "late_fee": None,
                "bill_status": "Unpaid",
            },
            previous=0,
            present=10,
            exception="None",
            reader_name="Reader",
        )

        self.assertIn("Penalty     : PHP    10.00", text)
        self.assertIn("After Due   : PHP   110.00", text)


if __name__ == "__main__":
    unittest.main()

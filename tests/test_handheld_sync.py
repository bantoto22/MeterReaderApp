import os
import gc
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import date, datetime, timedelta, timezone

from src.handheld_sync import (
    BackendApiClient,
    HandheldSyncDataAccess,
    SQLiteLocalSyncStore,
    SyncConfig,
    _build_bill_payload,
    format_sync_error,
)
from src.receipt import apply_authoritative_bill, build_receipt_text
import src.database as database


class FakeLocalStore:
    def __init__(self):
        self.queue = []
        self.audit = []
        self.cached = []
        self.cached_schedules = []
        self.cached_schedule_reader_id = None
        self.cached_schedule_range = (None, None)
        self._id = 1

    def ensure_schema(self):
        return

    def cache_reading_schedules(self, schedules, meter_reader_id, date_from, date_to):
        self.cached_schedules = list(schedules)
        self.cached_schedule_reader_id = meter_reader_id
        self.cached_schedule_range = (date_from, date_to)

    def cache_consumers(self, consumers):
        self.cached = list(consumers)

    def load_cached_consumers(self, zone_name=None):
        if not zone_name:
            return list(self.cached)
        return [c for c in self.cached if c.get("zone_name") == zone_name]

    @staticmethod
    def _combined_status(backend_status):
        return str(backend_status or "pending").lower()

    def _refresh_status(self, row):
        row["status"] = self._combined_status(row.get("backend_status"))

    def enqueue_operation(self, operation, payload, *, backend_status="pending"):
        row = {
            "id": self._id,
            "operation": operation,
            "operation_id": payload["operation_id"],
            "reading_id": payload["reading_id"],
            "consumer_id": payload["consumer_id"],
            "reading_date": payload["reading_date"],
            "payload": dict(payload),
            "status": self._combined_status(backend_status),
            "backend_status": backend_status,
            "retries": 0,
        }
        self._id += 1
        self.queue.append(row)
        return row

    def list_pending(self, target=None):
        return [q for q in self.queue if q["backend_status"] in ("pending", "failed")]

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
                q[f"{target or 'backend'}_status"] = "conflict"
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
        self.assigned_schedules = []
        self.context_by_consumer = {}
        self.assigned_consumer_calls = []

    def is_online(self):
        return self.online

    def load_reading_schedules(self, meter_reader_id, date_from, date_to, status="Scheduled"):
        return list(self.assigned_schedules)

    def load_assigned_consumers(self, meter_reader_id=None, zone_name=None, date_from=None, date_to=None):
        self.assigned_consumer_calls.append((meter_reader_id, zone_name, date_from, date_to))
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

    def save_reading_bundle(self, payload):
        reading = self.upsert_meter_reading(payload)
        return {"meterreading": reading, "bill": {"sync_id": payload.get("reading_id")}}

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

    def test_sync_error_explains_database_lock(self):
        diagnostic = format_sync_error("Updating the device cache", sqlite3.OperationalError("database is locked"))
        self.assertIn("Stage: Updating the device cache", diagnostic)
        self.assertIn("local SQLite database is busy", diagnostic)
        self.assertIn("Recommended action:", diagnostic)

    def test_backend_error_includes_http_status_and_route(self):
        class MissingRouteClient(BackendApiClient):
            def _req(self, method, path, *, query=None, payload=None):
                return 404, {"error": "Cannot GET /api/handheld/consumers"}

        client = MissingRouteClient(SyncConfig(backend_api_base_url="https://device.example.test"))
        with self.assertRaisesRegex(RuntimeError, r"HTTP 404 /api/handheld/consumers"):
            client.load_assigned_consumers()

    def test_manual_queue_does_not_upload_until_sync(self):
        self.remote.online = True
        result = self.dal.queueMeterReading({"consumer_id": 1, "present_reading": 100, "reading_date": "2026-05-08"})
        self.assertEqual(result["status"], "queued")
        self.assertEqual(len(self.remote.remote_rows), 0)
        self.assertEqual(len(self.local.list_pending()), 1)

    def test_online_save_uploads_immediately(self):
        self.remote.online = True
        result = self.dal.saveMeterReading({"consumer_id": 1, "present_reading": 100, "reading_date": "2026-05-08"})
        self.assertEqual(result["status"], "synced")
        self.assertEqual(len(self.remote.remote_rows), 1)
        self.assertEqual(len(self.local.list_pending()), 0)

    def test_concurrent_online_saves_are_serialized(self):
        self.remote.online = True
        active_writes = 0
        max_active_writes = 0
        counter_lock = threading.Lock()
        original_save = self.remote.save_reading_bundle

        def slow_save(payload):
            nonlocal active_writes, max_active_writes
            with counter_lock:
                active_writes += 1
                max_active_writes = max(max_active_writes, active_writes)
            try:
                time.sleep(0.05)
                return original_save(payload)
            finally:
                with counter_lock:
                    active_writes -= 1

        self.remote.save_reading_bundle = slow_save
        threads = [
            threading.Thread(
                target=self.dal.saveMeterReading,
                args=({"consumer_id": consumer_id, "present_reading": 100, "reading_date": "2026-05-08"},),
            )
            for consumer_id in (1, 2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(max_active_writes, 1)
        self.assertEqual(len(self.remote.remote_rows), 2)

    def test_reconnect_sync_flushes_queue(self):
        self.remote.online = False
        self.dal.saveMeterReading({"consumer_id": 2, "present_reading": 120, "reading_date": "2026-05-08"})
        self.remote.online = True
        result = self.dal.syncPendingReadings()
        self.assertEqual(result["synced"], 1)
        self.assertEqual(len(self.local.list_pending()), 0)

    def test_sync_worker_can_restart_after_stop(self):
        self.remote.online = False

        self.dal.start_sync_worker(interval_seconds=60)
        first_worker = self.dal._worker
        self.assertIsNotNone(first_worker)
        self.assertTrue(first_worker.is_alive())

        self.dal.stop_sync_worker()
        self.assertIsNone(self.dal._worker)

        self.dal.start_sync_worker(interval_seconds=60)
        second_worker = self.dal._worker
        self.assertIsNotNone(second_worker)
        self.assertIsNot(first_worker, second_worker)
        self.assertTrue(second_worker.is_alive())

        self.dal.stop_sync_worker()
        self.assertIsNone(self.dal._worker)

    def test_load_assigned_consumers_never_falls_back_to_an_unfiltered_dataset(self):
        self.remote.online = True

        def filtered_then_full(meter_reader_id=None, zone_name=None, date_from=None, date_to=None):
            self.remote.assigned_consumer_calls.append((meter_reader_id, zone_name, date_from, date_to))
            if meter_reader_id or zone_name or date_from or date_to:
                return []
            return [{"id": 9, "consumer_id": 9, "zone_name": "Zone 9"}]

        self.remote.load_assigned_consumers = filtered_then_full

        result = self.dal.loadAssignedConsumers(12, "Zone 1", "2026-08-01", "2026-08-31")

        self.assertEqual(result, [])
        self.assertEqual(
            self.remote.assigned_consumer_calls,
            [(12, "Zone 1", "2026-08-01", "2026-08-31")],
        )
        self.assertEqual(self.local.cached, [])

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

    def test_backend_api_login_and_bundle_use_authenticated_reader(self):
        class FakeBackendApiClient(BackendApiClient):
            def __init__(self):
                super().__init__(SyncConfig(backend_api_base_url="https://device.example.test"))
                self.calls = []

            def _req(self, method, path, *, query=None, payload=None):
                self.calls.append((method, path, query, payload))
                if path == "/api/login":
                    return 200, {
                        "success": True,
                        "user": {"id": 12, "username": "reader", "fullName": "Meter Reader", "role_id": 3},
                    }
                if path.endswith("/context"):
                    return 200, {
                        "consumer_id": 8,
                        "minimum_cubic": 10,
                        "minimum_rate": 100,
                        "excess_rate_per_cubic": 15,
                        "due_days": 15,
                        "late_fee": 10,
                    }
                if path == "/api/handheld/reading-bundles":
                    return 200, {"meterreading": {"reading_id": 44}, "bill": {"bill_id": 55}}
                return 404, {"message": "not found"}

        client = FakeBackendApiClient()
        user = client.authenticate_meter_reader("reader", "secret")
        result = client.save_reading_bundle(
            {
                "reading_id": "stable-sync-id",
                "consumer_id": 8,
                "previous_reading": 100,
                "present_reading": 112,
                "consumption": 12,
                "reading_date": "2026-08-02",
            }
        )

        self.assertEqual(user["account_id"], 12)
        self.assertEqual(result["meterreading"]["reading_id"], 44)
        self.assertEqual(result["bill"]["bill_id"], 55)
        bundle_call = next(call for call in client.calls if call[1] == "/api/handheld/reading-bundles")
        self.assertEqual(bundle_call[3]["reading"]["meter_reader_id"], 12)
        self.assertNotIn("bill", bundle_call[3])
        self.assertFalse(any(call[1].endswith("/context") for call in client.calls))

    def test_backend_api_base_url_accepts_api_suffix_without_double_prefix(self):
        class ApiSuffixedClient(BackendApiClient):
            def __init__(self):
                super().__init__(SyncConfig(backend_api_base_url="https://device.example.test/api"))
                self.urls = []

            def _req(self, method, path, *, query=None, payload=None, api_route=True):
                base_url = self._api_url if api_route else self._root_url
                normalized_path = path if path.startswith("/") else f"/{path}"
                if api_route and normalized_path.startswith("/api/"):
                    normalized_path = normalized_path[4:]
                self.urls.append(f"{base_url}{normalized_path}")
                if path == "/api/login":
                    return 200, {
                        "success": True,
                        "user": {"id": 12, "username": "reader", "fullName": "Meter Reader", "role_id": 3},
                    }
                if path == "/api/handheld/consumers":
                    return 200, []
                if path == "/health":
                    return 200, {}
                return 404, {"message": "not found"}

        client = ApiSuffixedClient()
        client.authenticate_meter_reader("reader", "secret")
        client.load_assigned_consumers(meter_reader_id=12)
        client.is_online()

        self.assertIn("https://device.example.test/api/login", client.urls)
        self.assertIn("https://device.example.test/api/handheld/consumers", client.urls)
        self.assertIn("https://device.example.test/health", client.urls)
        self.assertNotIn("https://device.example.test/api/api/login", client.urls)

    def test_queue_schema_migrates_legacy_pending_status_to_backend(self):
        handle = tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        legacy_status = "supa" + "base_status"
        legacy_synced = "supa" + "base_synced_at"
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    f"""
                    CREATE TABLE sync_queue_meter_readings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        operation TEXT NOT NULL,
                        operation_id TEXT NOT NULL UNIQUE,
                        reading_id TEXT NOT NULL,
                        consumer_id INTEGER NOT NULL,
                        reading_date TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        {legacy_status} TEXT NOT NULL DEFAULT 'pending',
                        retries INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        {legacy_synced} TEXT
                    )
                    """
                )
                conn.execute(
                    f"""INSERT INTO sync_queue_meter_readings
                    (operation, operation_id, reading_id, consumer_id, reading_date, payload, {legacy_status})
                    VALUES ('create', 'op-1', 'reading-1', 1, '2026-08-02', '{{}}', 'failed')"""
                )

            store = SQLiteLocalSyncStore(SyncConfig(backend_api_base_url="https://example.test"))
            store._db_path = db_path
            store.ensure_schema()

            with sqlite3.connect(db_path) as conn:
                migrated_status = conn.execute(
                    "SELECT backend_status FROM sync_queue_meter_readings WHERE operation_id = 'op-1'"
                ).fetchone()[0]
            self.assertEqual(migrated_status, "failed")
        finally:
            if "store" in locals():
                del store
            gc.collect()
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_cached_meter_reader_credentials_support_hashed_offline_login(self):
        original_db_path = database._db_path
        handle = tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        database._db_path = lambda: db_path
        try:
            database.init_db()
            database.cache_meter_reader_credentials(
                {
                    "id": 12,
                    "account_id": 12,
                    "reader_id": "12",
                    "username": "field.reader",
                    "name": "Field Reader",
                    "full_name": "Field Reader",
                    "role_id": 3,
                    "account_status": "Active",
                },
                "offline-secret",
            )

            with sqlite3.connect(db_path) as conn:
                stored_password = conn.execute(
                    "SELECT password FROM users WHERE username = 'field.reader'"
                ).fetchone()[0]

            self.assertTrue(stored_password.startswith("scrypt$"))
            self.assertNotIn("offline-secret", stored_password)
            self.assertEqual(database.authenticate_user("field.reader", "offline-secret")["account_id"], 12)
            self.assertIsNone(database.authenticate_user("field.reader", "wrong-password"))
        finally:
            database._db_path = original_db_path
            gc.collect()
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_replace_consumers_from_sync_marks_pulled_backend_reading_as_read(self):
        original_db_path = database._db_path
        handle = tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        database._db_path = lambda: db_path
        try:
            database.init_db()
            database.replace_consumers_from_sync(
                [
                    {
                        "id": 8,
                        "meter_no": "09-23-2233",
                        "acct_no": "04-11-123",
                        "name": "Charles Ivan De Vera",
                        "zone_name": "Zone 1",
                        "previous_reading": 77,
                        "latest_reading": 77,
                        "latest_reading_date": "2026-07-09",
                    }
                ]
            )

            rows = database.get_zone_consumers_with_status("Zone 1")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["is_read"], 1)
            self.assertEqual(rows[0]["reading_value"], 77)
        finally:
            database._db_path = original_db_path
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_replace_consumers_from_sync_persists_address_and_billing_period(self):
        original_db_path = database._db_path
        handle = tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        database._db_path = lambda: db_path
        try:
            database.init_db()
            database.replace_consumers_from_sync(
                [
                    {
                        "id": 8,
                        "meter_no": "09-23-2233",
                        "acct_no": "04-11-123",
                        "name": "Charles Ivan De Vera",
                        "address": "Barangay Uno",
                        "zone_name": "Zone 1",
                        "previous_reading": 77,
                        "classification_id": 1,
                        "classification_name": "Residential",
                        "minimum_cubic": 10,
                        "minimum_rate": 150,
                        "excess_rate_per_cubic": 15,
                        "due_days": 15,
                        "billing_month": "July 2026",
                        "date_covered_from": "2026-06-09 00:00:00",
                        "date_covered_to": "2026-07-09 00:00:00",
                        "connection_fee_components": [
                            {"code": "MTR", "amount": 25},
                            {"code": "CONN", "amount": 10},
                            {"code": "MEM", "amount": 5},
                        ],
                    }
                ]
            )

            consumer = database.search_consumer("09-23-2233", unread_only=False)

            self.assertEqual(consumer["address"], "Barangay Uno")
            self.assertEqual(consumer["billing_month"], "July 2026")
            self.assertEqual(consumer["date_covered_from"], "2026-06-09 00:00:00")
            self.assertEqual(consumer["date_covered_to"], "2026-07-09 00:00:00")
            self.assertEqual(consumer["water_meter_fee"], 25)
            self.assertEqual(consumer["connection_fee"], 10)
            self.assertEqual(consumer["membership_fee"], 5)
        finally:
            database._db_path = original_db_path
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_local_schedule_filter_limits_zones_and_read_status_by_selected_month(self):
        original_db_path = database._db_path
        handle = tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        database._db_path = lambda: db_path
        try:
            database.init_db()
            database.save_current_meter_reader(
                {
                    "account_id": 12,
                    "username": "juan.delacruz",
                    "full_name": "Juan Dela Cruz",
                    "contact_number": "09123456789",
                    "role_id": 3,
                    "account_status": "Active",
                }
            )
            database.replace_reading_schedules_from_sync(
                [
                    {
                        "Schedule_ID": 101,
                        "Schedule_Date": "2026-07-15",
                        "Zone_ID": 3,
                        "Zone_Name": "Zone 3",
                        "Meter_Reader_ID": 12,
                        "Meter_Reader_Name": "Juan Dela Cruz",
                        "Meter_Reader_Contact": "09123456789",
                        "Status": "Scheduled",
                    }
                ],
                meter_reader_id=12,
                date_from="2026-07-01",
                date_to="2026-07-31",
            )
            database.replace_consumers_from_sync(
                [
                    {
                        "id": 1,
                        "meter_no": "MTR-Z3-001",
                        "acct_no": "ACCT-Z3-001",
                        "name": "Zone Three Consumer",
                        "zone_name": "Zone 3",
                        "previous_reading": 20,
                    },
                    {
                        "id": 2,
                        "meter_no": "MTR-Z1-001",
                        "acct_no": "ACCT-Z1-001",
                        "name": "Zone One Consumer",
                        "zone_name": "Zone 1",
                        "previous_reading": 15,
                    },
                ]
            )

            zone_names = database.get_all_zone_names("2026-07-12", 12)
            self.assertEqual(zone_names, ["Zone 3"])

            scheduled_consumer = database.search_consumer("MTR-Z3-001", unread_only=True, schedule_date="2026-07-12", meter_reader_id=12)
            unscheduled_consumer = database.search_consumer("MTR-Z1-001", unread_only=True, schedule_date="2026-07-12", meter_reader_id=12)
            self.assertIsNotNone(scheduled_consumer)
            self.assertIsNone(unscheduled_consumer)

            rows_before = database.get_zone_consumers_with_status("Zone 3", "2026-07-12", 12)
            self.assertEqual(len(rows_before), 1)
            self.assertEqual(rows_before[0]["is_read"], 0)

            database.save_reading(1, 30, 10, "None", False, "2026-07-15")

            rows_after = database.get_zone_consumers_with_status("Zone 3", "2026-07-12", 12)
            self.assertEqual(rows_after[0]["is_read"], 1)

            unread_after = database.search_consumer("MTR-Z3-001", unread_only=True, schedule_date="2026-07-12", meter_reader_id=12)
            self.assertIsNone(unread_after)
        finally:
            database._db_path = original_db_path
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_multi_day_routes_are_reader_scoped_and_offline_ready_only_after_verification(self):
        original_db_path = database._db_path
        handle = tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        database._db_path = lambda: db_path
        try:
            database.init_db()
            database.replace_reading_schedules_from_sync(
                [
                    {
                        "schedule_id": 201,
                        "start_date": "2026-07-30",
                        "due_date": "2026-08-10",
                        "billing_month": "August 2026",
                        "zone_name": "Route A",
                        "meter_reader_id": 12,
                        "status": "In Progress",
                    },
                    {
                        "schedule_id": 202,
                        "start_date": "2026-08-01",
                        "due_date": "2026-08-15",
                        "billing_month": "August 2026",
                        "zone_name": "Private Route",
                        "meter_reader_id": 13,
                        "status": "Scheduled",
                    },
                ],
                meter_reader_id=12,
                date_from="2026-07-01",
                date_to="2026-08-31",
            )
            database.replace_consumers_from_sync(
                [
                    {"id": 1, "meter_no": "MTR-A-1", "acct_no": "A-1", "name": "Assigned", "zone_name": "Route A"},
                    {"id": 2, "meter_no": "MTR-P-1", "acct_no": "P-1", "name": "Other Reader", "zone_name": "Private Route"},
                ]
            )

            routes = database.get_assigned_routes(12)
            self.assertEqual([route["schedule_id"] for route in routes], [201])
            self.assertIsNone(routes[0]["cache_verified_at"])
            self.assertEqual(database.get_all_zone_names("2026-08-05", 12), ["Route A"])
            self.assertIsNone(database.search_consumer("MTR-P-1", False, "2026-08-05", 12))

            self.assertTrue(database.mark_route_cache_verified(201, 12, 1))
            self.assertFalse(database.mark_route_cache_verified(202, 12, 1))
            verified = database.get_assigned_routes(12)[0]
            self.assertEqual(verified["cached_consumer_count"], 1)
            self.assertIsNotNone(verified["cache_verified_at"])
        finally:
            database._db_path = original_db_path
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_route_reading_date_stays_in_selected_billing_window(self):
        from src.qt_hybrid_app import _route_reading_date

        selected = _route_reading_date(
            "2026-07-01",
            "2026-07-15",
            "2026-07-20",
            today=date(2026, 8, 6),
        )

        self.assertEqual(selected, date(2026, 7, 15))

    def test_display_routes_group_matching_zone_schedules_without_losing_ids(self):
        from src.qt_hybrid_app import _group_route_rows, _zone_schedule

        grouped = _group_route_rows(
            [
                {
                    "schedule_id": 401, "meter_reader_id": 12, "start_date": "2026-09-10", "due_date": "2026-09-12",
                    "billing_month": "September 2026", "zone_name": "Zone 1",
                    "display_status": "Scheduled", "cache_verified_at": "2026-09-01", "cached_consumer_count": 4,
                },
                {
                    "schedule_id": 402, "meter_reader_id": 12, "start_date": "2026-09-10", "due_date": "2026-09-12",
                    "billing_month": "September 2026", "zone_name": "Zone 2",
                    "display_status": "Scheduled", "cache_verified_at": "2026-09-01", "cached_consumer_count": 3,
                },
                {
                    "schedule_id": 499, "meter_reader_id": 12, "start_date": "2026-09-11", "due_date": "2026-09-13",
                    "billing_month": "September 2026", "zone_name": "Zone 9",
                    "display_status": "Scheduled", "cache_verified_at": None, "cached_consumer_count": 0,
                },
                {
                    "schedule_id": 498, "meter_reader_id": 13, "start_date": "2026-09-10", "due_date": "2026-09-12",
                    "billing_month": "September 2026", "zone_name": "Zone 8",
                    "display_status": "Scheduled", "cache_verified_at": None, "cached_consumer_count": 0,
                },
            ]
        )

        self.assertEqual(len(grouped), 3)
        route = grouped[0]
        self.assertEqual(route["zones"], ["All zones", "Zone 1", "Zone 2"])
        self.assertEqual(_zone_schedule(route, "Zone 1")["scheduleId"], "401")
        self.assertEqual(_zone_schedule(route, "Zone 2")["scheduleId"], "402")
        self.assertEqual(_zone_schedule(route, "", "402")["zoneName"], "Zone 2")
        self.assertTrue(route["offlineReady"])

    def test_expired_unread_schedules_are_carried_into_current_route(self):
        from src.qt_hybrid_app import _group_route_rows, _zone_schedule

        grouped = _group_route_rows(
            [
                {
                    "schedule_id": 510, "meter_reader_id": 12,
                    "start_date": "2026-07-01", "due_date": "2026-07-03",
                    "billing_month": "July 2026", "zone_name": "Old Zone",
                    "display_status": "Overdue", "unread_count": 2,
                    "cache_verified_at": "2026-07-01", "cached_consumer_count": 2,
                },
                {
                    "schedule_id": 511, "meter_reader_id": 12,
                    "start_date": "2026-07-01", "due_date": "2026-07-03",
                    "billing_month": "July 2026", "zone_name": "Finished Zone",
                    "display_status": "Overdue", "unread_count": 0,
                    "cache_verified_at": "2026-07-01", "cached_consumer_count": 2,
                },
                {
                    "schedule_id": 601, "meter_reader_id": 12,
                    "start_date": "2026-08-15", "due_date": "2026-08-17",
                    "billing_month": "August 2026", "zone_name": "Current Zone",
                    "display_status": "In Progress", "unread_count": 3,
                    "cache_verified_at": "2026-08-14", "cached_consumer_count": 3,
                },
                {
                    "schedule_id": 710, "meter_reader_id": 13,
                    "start_date": "2026-07-01", "due_date": "2026-07-03",
                    "billing_month": "July 2026", "zone_name": "Other Reader Zone",
                    "display_status": "Overdue", "unread_count": 4,
                    "cache_verified_at": "2026-07-01", "cached_consumer_count": 4,
                },
            ],
            today=date(2026, 8, 16),
        )

        current = next(group for group in grouped if group["billingMonth"] == "August 2026")
        self.assertEqual(current["carryOverUnreadCount"], 2)
        self.assertEqual(current["zones"], ["All zones", "Old Zone", "Current Zone"])
        self.assertEqual(_zone_schedule(current, "Old Zone")["scheduleId"], "510")
        self.assertTrue(_zone_schedule(current, "Old Zone")["isCarryOver"])
        self.assertNotIn("Finished Zone", current["zones"])
        self.assertNotIn("Other Reader Zone", current["zones"])

    def test_assignment_deadline_and_completion_are_scoped_to_schedule(self):
        original_db_path = database._db_path
        handle = tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        database._db_path = lambda: db_path
        try:
            database.init_db()
            today = date.today()
            scheduled = today - timedelta(days=5)
            due = today - timedelta(days=3)
            database.replace_reading_schedules_from_sync(
                [{
                    "schedule_id": 301,
                    "start_date": scheduled.isoformat(),
                    "due_date": due.isoformat(),
                    "billing_month": today.strftime("%B %Y"),
                    "zone_name": "Late Route",
                    "meter_reader_id": 12,
                    "status": "Completed",
                }],
                12, scheduled.isoformat(), today.isoformat(),
            )
            database.replace_consumers_from_sync(
                [{
                    "id": 50, "meter_no": "MTR-LATE-1", "acct_no": "LATE-1",
                    "name": "Missed Consumer", "zone_name": "Late Route",
                    "schedule_id": 301, "schedule_date": scheduled.isoformat(),
                    "schedule_due_date": due.isoformat(), "is_read": False,
                    "reading_status": "pending", "reading_sync_status": "pending",
                }]
            )

            self.assertEqual([row["schedule_id"] for row in database.get_assigned_routes(12)], [301])
            pending = database.get_zone_consumers_with_status(
                "Late Route", today.isoformat(), 12, schedule_id=301,
            )[0]
            self.assertEqual(pending["deadline_status"], "Overdue 3d")

            future_due = today + timedelta(days=2)
            database.replace_reading_schedules_from_sync(
                [{
                    "schedule_id": 302, "start_date": today.isoformat(),
                    "due_date": future_due.isoformat(), "billing_month": today.strftime("%B %Y"),
                    "zone_name": "Late Route", "meter_reader_id": 12, "status": "Scheduled",
                }],
                12, today.isoformat(), future_due.isoformat(),
            )
            database.replace_consumers_from_sync(
                [{
                    "id": 50, "meter_no": "MTR-LATE-1", "acct_no": "LATE-1",
                    "name": "Missed Consumer", "zone_name": "Late Route", "schedule_id": 302,
                    "is_read": False, "reading_status": "pending", "reading_sync_status": "pending",
                }]
            )

            database.save_reading(
                50, 110, 10, reading_date=today.isoformat(), schedule_id=301,
                schedule_date=scheduled.isoformat(), schedule_due_date=due.isoformat(),
                billing_cycle=today.strftime("%B %Y"), sync_reading_id="reading-301",
            )
            saved = database.get_zone_consumers_with_status(
                "Late Route", today.isoformat(), 12, schedule_id=301,
            )[0]
            self.assertEqual(saved["deadline_status"], "Completed")
            self.assertEqual(saved["reading_sync_status"], "pending")
            other_schedule = database.get_zone_consumers_with_status(
                "Late Route", today.isoformat(), 12, schedule_id=302,
            )[0]
            self.assertEqual(other_schedule["deadline_status"], "Due in 2d")

            database.update_reading_sync_state("reading-301", "conflict", "rejected")
            restored = database.get_zone_consumers_with_status(
                "Late Route", today.isoformat(), 12, schedule_id=301,
            )[0]
            self.assertEqual(restored["deadline_status"], "Overdue 3d")
            self.assertEqual(restored["reading_status"], "rejected")
        finally:
            database._db_path = original_db_path
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_receipt_history_persists_all_records_and_filters_by_reading_month(self):
        original_db_path = database._db_path
        handle = tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        database._db_path = lambda: db_path
        try:
            database.init_db()
            database.replace_consumers_from_sync(
                [{
                    "id": 70, "meter_no": "MTR-HISTORY", "acct_no": "HISTORY-1",
                    "name": "History Consumer", "zone_name": "History Zone", "previous_reading": 0,
                }]
            )
            for index in range(15):
                reading_month = 7 if index < 10 else 8
                reading_date = date(2026, reading_month, (index % 10) + 1).isoformat()
                reading_id = database.save_reading(70, index + 1, 1, reading_date=reading_date)
                database.save_receipt_print(
                    70, f"Receipt body {index}", index, index + 1, 1,
                    reading_id=reading_id, acct_no="HISTORY-1",
                    consumer_name="History Consumer", meter_no="MTR-HISTORY",
                    zone_name="History Zone",
                )

            all_rows = database.list_receipt_print_history()
            july_rows = database.list_receipt_print_history(month="2026-07")
            august_rows = database.list_receipt_print_history(month="2026-08")

            self.assertEqual(len(all_rows), 15)
            self.assertEqual(len(july_rows), 10)
            self.assertEqual(len(august_rows), 5)
            self.assertEqual(database.list_receipt_print_months(), ["2026-08", "2026-07"])
            self.assertEqual(len(database.list_receipt_print_history("body 12", month="2026-08")), 1)
        finally:
            database._db_path = original_db_path
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_local_schedule_queries_do_not_expose_cached_routes_without_assignment(self):
        original_db_path = database._db_path
        handle = tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        database._db_path = lambda: db_path
        try:
            database.init_db()
            database.save_current_meter_reader(
                {
                    "account_id": 12,
                    "username": "juan.delacruz",
                    "full_name": "Juan Dela Cruz",
                    "contact_number": "09123456789",
                    "role_id": 3,
                    "account_status": "Active",
                }
            )
            database.replace_consumers_from_sync(
                [
                    {
                        "id": 1,
                        "meter_no": "MTR-Z3-001",
                        "acct_no": "ACCT-Z3-001",
                        "name": "Zone Three Consumer",
                        "zone_name": "Zone 3",
                        "previous_reading": 20,
                    },
                    {
                        "id": 2,
                        "meter_no": "MTR-Z1-001",
                        "acct_no": "ACCT-Z1-001",
                        "name": "Zone One Consumer",
                        "zone_name": "Zone 1",
                        "previous_reading": 15,
                    },
                ]
            )

            zone_names = database.get_all_zone_names("2026-07-12", 12)
            self.assertEqual(zone_names, [])

            consumer = database.search_consumer("MTR-Z3-001", unread_only=True, schedule_date="2026-07-12", meter_reader_id=12)
            self.assertIsNone(consumer)

            rows = database.get_zone_consumers_with_status("Zone 3", "2026-07-12", 12)
            self.assertEqual(rows, [])
        finally:
            database._db_path = original_db_path
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_replace_consumers_from_sync_skips_consumers_without_meter_numbers(self):
        original_db_path = database._db_path
        handle = tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        database._db_path = lambda: db_path
        try:
            database.init_db()
            mirrored = database.replace_consumers_from_sync(
                [
                    {
                        "id": 33,
                        "meter_no": None,
                        "acct_no": "ACCT-Z3-033",
                        "name": "No Meter Yet",
                        "zone_name": "Zone 3",
                        "previous_reading": 0,
                    }
                ]
            )

            rows = database.get_zone_consumers_with_status("Zone 3")

            self.assertEqual(mirrored, 0)
            self.assertEqual(rows, [])
        finally:
            database._db_path = original_db_path
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_bill_payload_does_not_penalize_current_bill_before_due_date(self):
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
        self.assertEqual(payload["penalty"], 0.0)
        self.assertEqual(payload["total_after_due_date"], 100.0)

    def test_bill_payload_sums_each_unpaid_month_without_compounding(self):
        payload = _build_bill_payload(
            {
                "reading_id": "7f00dbb6-656d-43b4-b4db-2bb206af9d22",
                "consumer_id": 42,
                "present_reading": 1,
                "previous_reading": 0,
                "consumption": 1,
                "reading_date": "2026-07-08",
            },
            {
                "minimum_cubic": 0,
                "minimum_rate": 0,
                "excess_rate_per_cubic": 40,
                "due_days": 15,
                "late_fee": None,
                "unpaid_bills": [
                    {
                        "bill_id": "jan",
                        "billing_month": "January 2026",
                        "original_amount": 20,
                        "due_date": "2026-02-01",
                        "own_penalty": 2,
                        "status": "Unpaid",
                    },
                    {
                        "bill_id": "feb",
                        "billing_month": "February 2026",
                        "original_amount": 22,
                        "due_date": "2026-03-01",
                        "own_penalty": 2.2,
                        "status": "Unpaid",
                    },
                ],
            },
            99,
        )

        self.assertEqual(payload["amount_due"], 86.2)
        self.assertEqual(payload["previous_balance"], 42.0)
        self.assertEqual(payload["previous_penalty"], 4.2)
        self.assertEqual(payload["penalty"], 0.0)
        self.assertEqual(payload["total_after_due_date"], 86.2)

    def test_bill_payload_applies_penalty_only_to_overdue_current_principal(self):
        payload = _build_bill_payload(
            {
                "reading_id": "7f00dbb6-656d-43b4-b4db-2bb206af9d23",
                "consumer_id": 42,
                "present_reading": 8,
                "previous_reading": 5,
                "consumption": 3,
                "reading_date": "2026-07-09",
                "due_date": "2026-07-08",
            },
            {
                "minimum_cubic": 0,
                "minimum_rate": 0,
                "excess_rate_per_cubic": 10,
                "due_days": 15,
                "late_fee": None,
            },
            100,
        )

        self.assertEqual(payload["amount_due"], 30.0)
        self.assertEqual(payload["previous_balance"], 0.0)
        self.assertEqual(payload["previous_penalty"], 0.0)
        self.assertEqual(payload["penalty"], 3.0)
        self.assertEqual(payload["total_after_due_date"], 33.0)

    def test_bill_payload_includes_fees_but_never_penalizes_them(self):
        payload = _build_bill_payload(
            {
                "reading_id": "fee-rule-current",
                "consumer_id": 42,
                "present_reading": 10,
                "previous_reading": 0,
                "consumption": 10,
                "reading_date": "2026-07-09",
                "due_date": "2026-07-08",
            },
            {
                "minimum_cubic": 10,
                "minimum_rate": 100,
                "excess_rate_per_cubic": 15,
                "late_fee": 10,
                "connection_fee_components": [
                    {"component_code": "MTR", "component_amount": 25},
                    {"fee_code": "CONN", "fee_amount": 10},
                    {"type": "MEM", "value": 5},
                ],
            },
            101,
        )

        self.assertEqual(payload["meter_maintenance_fee"], 25.0)
        self.assertEqual(payload["connection_fee"], 10.0)
        self.assertEqual(payload["membership_fee"], 5.0)
        self.assertEqual(payload["amount_due"], 140.0)
        self.assertEqual(payload["penalty"], 10.0)
        self.assertEqual(payload["total_after_due_date"], 150.0)

    def test_prior_unpaid_fees_are_excluded_from_reconstructed_penalty(self):
        payload = _build_bill_payload(
            {
                "reading_id": "fee-rule-prior",
                "consumer_id": 42,
                "present_reading": 0,
                "previous_reading": 0,
                "consumption": 0,
                "reading_date": "2026-07-09",
            },
            {
                "minimum_cubic": 0,
                "minimum_rate": 0,
                "excess_rate_per_cubic": 10,
                "late_fee": 10,
                "unpaid_bills": [{
                    "bill_id": "prior-with-fees",
                    "original_amount": 140,
                    "water_charge": 100,
                    "meter_maintenance_fee": 25,
                    "connection_fee": 10,
                    "membership_fee": 5,
                    "due_date": "2026-06-01",
                    "status": "Unpaid",
                }],
            },
            102,
        )

        self.assertEqual(payload["previous_balance"], 140.0)
        self.assertEqual(payload["previous_penalty"], 10.0)
        self.assertEqual(payload["amount_due"], 150.0)

    def test_receipt_total_uses_current_reading_bill_not_stale_amount_due(self):
        text = build_receipt_text(
            {
                "id": 42,
                "acct_no": "09-99-0000",
                "name": "Test Consumer",
                "zone_name": "Zone 1",
                "classification_id": 1,
                "classification_name": "Residential",
                "meter_no": "MTR-TEST",
                "minimum_cubic": 0,
                "minimum_rate": 0,
                "excess_rate_per_cubic": 10,
                "due_days": 15,
                "amount_due": 339,
                "late_fee": None,
                "bill_status": "Paid",
            },
            previous=24,
            present=25,
            exception="None",
            reader_name="Reader",
            reading_date="2026-07-06",
        )

        self.assertIn("Current Bill: PHP    10.00", text)
        self.assertIn("Prev Bill  : PHP 0.00", text)
        self.assertIn("Bill Month : July 2026", text)
        self.assertIn("Coverage   : 2026-07-01 to", text)
        self.assertIn("TOTAL DUE   : PHP    10.00", text)
        self.assertNotIn("TOTAL DUE   : PHP   339.00", text)

    def test_receipt_lists_fees_and_penalizes_only_the_water_charge(self):
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
                "due_date": "2026-07-08",
                "late_fee": 10,
                "bill_status": "Unpaid",
                "connection_fee_components": {
                    "MTR": 25,
                    "CONN": {"amount": 10},
                    "MEM": {"fee_amount": 5},
                },
            },
            previous=0,
            present=10,
            exception="None",
            reader_name="Reader",
            reading_date="2026-07-09",
        )

        self.assertIn("Water Meter Fee: PHP    25.00", text)
        self.assertIn("Connection Fee: PHP    10.00", text)
        self.assertIn("Membership Fee: PHP     5.00", text)
        self.assertIn("Due Pen(10%): PHP    10.00", text)
        self.assertIn("TOTAL DUE   : PHP   140.00", text)
        self.assertIn("AFTER DUE   : PHP   150.00", text)

    def test_receipt_total_includes_previous_balance(self):
        text = build_receipt_text(
            {
                "id": 42,
                "acct_no": "09-99-0000",
                "name": "Test Consumer",
                "zone_name": "Zone 1",
                "classification_id": 1,
                "classification_name": "Residential",
                "meter_no": "MTR-TEST",
                "minimum_cubic": 0,
                "minimum_rate": 0,
                "excess_rate_per_cubic": 10,
                "due_days": 15,
                "previous_balance": 50,
                "previous_penalty": 5,
                "late_fee": None,
                "bill_status": "Unpaid",
            },
            previous=24,
            present=25,
            exception="None",
            reader_name="Reader",
            reading_date="2026-07-06",
        )

        self.assertIn("Current Bill: PHP    10.00", text)
        self.assertIn("Previous    : PHP    50.00", text)
        self.assertIn("Prev Pen(10%): PHP     5.00", text)
        self.assertIn("Prev Bill  : PHP 50.00", text)
        self.assertIn("TOTAL DUE   : PHP    65.00", text)
        self.assertIn("AFTER DUE   : PHP    65.00", text)

    def test_receipt_does_not_treat_rolled_amount_due_as_monthly_principal(self):
        text = build_receipt_text(
            {
                "id": 42,
                "acct_no": "09-99-0000",
                "name": "Test Consumer",
                "zone_name": "Zone 1",
                "classification_id": 1,
                "classification_name": "Residential",
                "meter_no": "MTR-TEST",
                "minimum_cubic": 0,
                "minimum_rate": 0,
                "excess_rate_per_cubic": 10,
                "due_days": 15,
                "amount_due": 100,
                "penalty": 10,
                "total_after_due_date": 110,
                "late_fee": None,
                "bill_status": "Unpaid",
            },
            previous=24,
            present=25,
            exception="None",
            reader_name="Reader",
            reading_date="2026-07-06",
        )

        self.assertIn("Current Bill: PHP    10.00", text)
        self.assertIn("Previous    : PHP     0.00", text)
        self.assertIn("Prev Pen(10%): PHP     0.00", text)
        self.assertIn("TOTAL DUE   : PHP    10.00", text)
        self.assertIn("AFTER DUE   : PHP    10.00", text)

    def test_receipt_applies_previous_penalty_separately_from_current_due_penalty(self):
        text = build_receipt_text(
            {
                "id": 42,
                "acct_no": "09-99-0000",
                "name": "Test Consumer",
                "zone_name": "Zone 1",
                "classification_id": 1,
                "classification_name": "Residential",
                "meter_no": "MTR-TEST",
                "minimum_cubic": 0,
                "minimum_rate": 0,
                "excess_rate_per_cubic": 40,
                "due_days": 15,
                "previous_balance": 360,
                "previous_penalty": 36,
                "due_date": "2026-07-05",
                "late_fee": None,
                "bill_status": "Unpaid",
            },
            previous=0,
            present=1,
            exception="None",
            reader_name="Reader",
            reading_date="2026-07-06",
        )

        current_line = "Current Bill: PHP    40.00"
        due_penalty_line = "Due Pen(10%): PHP     4.00"
        previous_line = "Previous    : PHP   360.00"
        previous_penalty_line = "Prev Pen(10%): PHP    36.00"

        self.assertIn(current_line, text)
        self.assertIn(due_penalty_line, text)
        self.assertIn(previous_line, text)
        self.assertIn(previous_penalty_line, text)
        self.assertLess(text.index(current_line), text.index(due_penalty_line))
        self.assertLess(text.index(due_penalty_line), text.index(previous_line))
        self.assertLess(text.index(previous_line), text.index(previous_penalty_line))
        self.assertIn("TOTAL DUE   : PHP   436.00", text)
        self.assertIn("AFTER DUE   : PHP   440.00", text)

    def test_receipt_keeps_server_previous_totals_without_rolling_again(self):
        text = build_receipt_text(
            {
                "id": 42,
                "acct_no": "09-99-0000",
                "name": "Test Consumer",
                "zone_name": "Zone 1",
                "classification_id": 1,
                "classification_name": "Residential",
                "meter_no": "MTR-TEST",
                "minimum_cubic": 0,
                "minimum_rate": 0,
                "excess_rate_per_cubic": 10,
                "due_days": 15,
                "amount_due": 175.2,
                "previous_balance": 132,
                "previous_penalty": 13.2,
                "late_fee": None,
                "bill_status": "Unpaid",
            },
            previous=5,
            present=8,
            exception="None",
            reader_name="Reader",
            reading_date="2026-07-09",
        )

        self.assertIn("Current Bill: PHP    30.00", text)
        self.assertIn("Previous    : PHP   132.00", text)
        self.assertIn("Prev Pen(10%): PHP    13.20", text)
        self.assertIn("TOTAL DUE   : PHP   175.20", text)
        self.assertIn("AFTER DUE   : PHP   175.20", text)

    def test_receipt_does_not_apply_current_penalty_before_due_date(self):
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
                "late_fee": None,
                "bill_status": "Unpaid",
            },
            previous=0,
            present=10,
            exception="None",
            reader_name="Reader",
        )

        self.assertIn("Due Pen(10%): PHP     0.00", text)
        self.assertIn("AFTER DUE   : PHP   100.00", text)

    def test_receipt_uses_authoritative_backend_bill_totals(self):
        consumer = apply_authoritative_bill(
            {
                "id": 42,
                "acct_no": "09-99-0000",
                "name": "Test Consumer",
                "classification_id": 1,
                "classification_name": "Residential",
                "meter_no": "MTR-TEST",
                "minimum_cubic": 0,
                "minimum_rate": 0,
                "excess_rate_per_cubic": 40,
                "due_days": 15,
            },
            {
                "billing_month": "March 2026",
                "current_month_amount": 40,
                "previous_balance": 42,
                "previous_penalty": 4.2,
                "current_penalty": 0,
                "amount_due": 86.2,
                "total_after_due_date": 86.2,
                "due_date": "2026-03-20",
                "status": "Unpaid",
            },
        )

        text = build_receipt_text(
            consumer, previous=0, present=1, exception="None", reader_name="Reader", reading_date="2026-03-08"
        )

        self.assertIn("Current Bill: PHP    40.00", text)
        self.assertIn("Previous    : PHP    42.00", text)
        self.assertIn("Prev Pen(10%): PHP     4.20", text)
        self.assertIn("TOTAL DUE   : PHP    86.20", text)
        self.assertIn("AFTER DUE   : PHP    86.20", text)

    def test_assignment_account_numbers_order_search_and_reading_metadata(self):
        original_db_path = database._db_path
        handle = tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        database._db_path = lambda: db_path
        try:
            database.init_db()
            today = date.today().isoformat()
            database.replace_reading_schedules_from_sync(
                [{
                    "schedule_id": 801, "start_date": today, "due_date": today,
                    "billing_month": "August 2026", "zone_name": "Ordered Zone",
                    "meter_reader_id": 12, "status": "Scheduled",
                }, {
                    "schedule_id": 802, "start_date": today, "due_date": today,
                    "billing_month": "August 2026", "zone_name": "Natural Zone",
                    "meter_reader_id": 12, "status": "Scheduled",
                }],
                12, today, today,
            )
            account_numbers = [
                "02-11-152-A2", "02-11-153-0", "02-11-152-0",
                "02-11-151-0", "02-11-152-A1",
            ]
            ordered_rows = []
            for index, acct_no in enumerate(account_numbers, start=1):
                ordered_rows.append({
                    "id": index, "consumer_id": index, "meter_no": f"MTR-O-{index}",
                    "acct_no": acct_no, "name": f"Ordered {index}",
                    "zone_name": "Ordered Zone", "schedule_id": 801,
                    "assignment_order": 6 - index, "reading_route_id": "ROUTE-801",
                    "schedule_date": today, "schedule_due_date": today,
                    "billing_cycle": "August 2026",
                })
            natural_rows = []
            for index, acct_no in enumerate(account_numbers, start=11):
                natural_rows.append({
                    "id": index, "consumer_id": index, "meter_no": f"MTR-N-{index}",
                    "acct_no": acct_no, "name": f"Natural {index}",
                    "zone_name": "Natural Zone", "schedule_id": 802,
                    "assignment_order": None, "reading_route_id": "ROUTE-802",
                    "schedule_date": today, "schedule_due_date": today,
                    "billing_cycle": "August 2026",
                })
            database.replace_consumers_from_sync(ordered_rows + natural_rows)

            ordered = database.get_zone_consumers_with_status(
                "Ordered Zone", today, 12, schedule_id=801,
            )
            self.assertEqual([row["assignment_order"] for row in ordered], [1, 2, 3, 4, 5])
            natural = database.get_zone_consumers_with_status(
                "Natural Zone", today, 12, schedule_id=802,
            )
            self.assertEqual(
                [row["acct_no"] for row in natural],
                ["02-11-151-0", "02-11-152-0", "02-11-152-A1", "02-11-152-A2", "02-11-153-0"],
            )
            nearby = database.search_consumers_by_zone(
                "02-11-152", "Natural Zone", unread_only=True,
                schedule_date=today, meter_reader_id=12, schedule_id=802,
            )
            self.assertEqual([row["acct_no"] for row in nearby], ["02-11-152-0", "02-11-152-A1", "02-11-152-A2"])
            self.assertTrue(all(row["is_nearby_connection"] for row in nearby))

            reading_id = database.save_reading(
                1, 100, 10, reading_date=today, schedule_id=801,
                reading_route_id="ROUTE-801", assignment_order=5,
            )
            with sqlite3.connect(db_path) as conn:
                stored = conn.execute(
                    "SELECT reading_route_id, assignment_order, schedule_id, consumer_id FROM readings WHERE id = ?",
                    (reading_id,),
                ).fetchone()
            self.assertEqual(stored, ("ROUTE-801", 5, 801, 1))
        finally:
            database._db_path = original_db_path
            gc.collect()
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_assignment_cache_survives_restart_with_exact_account_and_order(self):
        handle = tempfile.NamedTemporaryFile(dir=os.getcwd(), suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        try:
            cfg = SyncConfig(backend_api_base_url="https://example.test")
            store = SQLiteLocalSyncStore(cfg)
            store._db_path = db_path
            store.ensure_schema()
            store.cache_consumers([
                {
                    "id": 21, "consumer_id": 21, "meter_no": "MTR-21", "acct_no": "02-11-152-A1",
                    "name": "Connection A1", "zone_name": "Zone A", "schedule_id": 901,
                    "assignment_order": 2, "reading_route_id": "ROUTE-901",
                    "meter_maintenance_fee": 25, "connection_fee": 10, "membership_fee": 5,
                },
                {
                    "id": 20, "consumer_id": 20, "meter_no": "MTR-20", "acct_no": "02-11-152-0",
                    "name": "Main Connection", "zone_name": "Zone A", "schedule_id": 901,
                    "assignment_order": 1, "reading_route_id": "ROUTE-901",
                },
            ])
            del store

            reopened = SQLiteLocalSyncStore(cfg)
            reopened._db_path = db_path
            reopened.ensure_schema()
            cached = reopened.load_cached_consumers("Zone A")
            self.assertEqual([row["acct_no"] for row in cached], ["02-11-152-0", "02-11-152-A1"])
            self.assertEqual([row["assignment_order"] for row in cached], [1, 2])
            self.assertTrue(all(row["reading_route_id"] == "ROUTE-901" for row in cached))
            self.assertTrue(all(row["schedule_id"] == 901 for row in cached))
            self.assertEqual(cached[1]["water_meter_fee"], 25)
            self.assertEqual(cached[1]["connection_fee"], 10)
            self.assertEqual(cached[1]["membership_fee"], 5)
        finally:
            gc.collect()
            try:
                os.remove(db_path)
            except OSError:
                pass

    def test_receipt_uses_latest_reading_date_for_billing_period_start(self):
        text = build_receipt_text(
            {
                "id": 42,
                "acct_no": "09-99-0000",
                "name": "Test Consumer",
                "zone_name": "Zone 1",
                "classification_id": 1,
                "classification_name": "Residential",
                "meter_no": "MTR-TEST",
                "minimum_cubic": 0,
                "minimum_rate": 0,
                "excess_rate_per_cubic": 10,
                "due_days": 15,
                "late_fee": None,
                "bill_status": "Paid",
                "latest_reading_date": "2026-07-02",
            },
            previous=24,
            present=25,
            exception="None",
            reader_name="Reader",
            reading_date="2026-07-06",
        )

        self.assertIn("Coverage   : 2026-07-02 to", text)


if __name__ == "__main__":
    unittest.main()

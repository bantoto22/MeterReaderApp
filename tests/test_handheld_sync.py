import os
import gc
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone

from src.handheld_sync import (
    BackendApiClient,
    HandheldSyncDataAccess,
    SQLiteLocalSyncStore,
    SyncConfig,
    _build_bill_payload,
    format_sync_error,
)
from src.receipt import build_receipt_text
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
        bundle_call = next(call for call in client.calls if call[1] == "/api/handheld/reading-bundles")
        self.assertEqual(bundle_call[3]["reading"]["meter_reader_id"], 12)
        self.assertEqual(bundle_call[3]["bill"]["sync_id"], "stable-sync-id")

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
                    }
                ]
            )

            consumer = database.search_consumer("09-23-2233", unread_only=False)

            self.assertEqual(consumer["address"], "Barangay Uno")
            self.assertEqual(consumer["billing_month"], "July 2026")
            self.assertEqual(consumer["date_covered_from"], "2026-06-09 00:00:00")
            self.assertEqual(consumer["date_covered_to"], "2026-07-09 00:00:00")
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

    def test_bill_payload_applies_previous_penalty_separately_from_current_due_penalty(self):
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
                "bill_status": "Unpaid",
                "previous_balance": 360,
            },
            99,
        )

        self.assertEqual(payload["amount_due"], 436.0)
        self.assertEqual(payload["previous_balance"], 360.0)
        self.assertEqual(payload["previous_penalty"], 36.0)
        self.assertEqual(payload["penalty"], 4.0)
        self.assertEqual(payload["total_after_due_date"], 440.0)

    def test_bill_payload_rolls_unpaid_amount_into_next_previous_balance(self):
        payload = _build_bill_payload(
            {
                "reading_id": "7f00dbb6-656d-43b4-b4db-2bb206af9d23",
                "consumer_id": 42,
                "present_reading": 8,
                "previous_reading": 5,
                "consumption": 3,
                "reading_date": "2026-07-09",
            },
            {
                "minimum_cubic": 0,
                "minimum_rate": 0,
                "excess_rate_per_cubic": 10,
                "due_days": 15,
                "late_fee": None,
                "bill_status": "Unpaid",
                "amount_due": 175.2,
                "previous_balance": 132,
                "previous_penalty": 13.2,
            },
            100,
        )

        self.assertEqual(payload["amount_due"], 208.2)
        self.assertEqual(payload["previous_balance"], 162.0)
        self.assertEqual(payload["previous_penalty"], 16.2)
        self.assertEqual(payload["penalty"], 3.0)
        self.assertEqual(payload["total_after_due_date"], 211.2)

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
        self.assertIn("Prev Bill    : PHP 0.00", text)
        self.assertIn("Billing Month: July 2026", text)
        self.assertIn("Billing Period: 2026-07-01 to 2026-07-06", text)
        self.assertIn("TOTAL AMOUNT: PHP    10.00", text)
        self.assertNotIn("TOTAL AMOUNT: PHP   339.00", text)

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
        self.assertIn("Prev Penalty(10%): PHP     5.00", text)
        self.assertIn("Prev Bill    : PHP 50.00", text)
        self.assertIn("TOTAL AMOUNT: PHP    65.00", text)
        self.assertIn("After Due   : PHP    66.00", text)

    def test_receipt_total_includes_unpaid_previous_bill(self):
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
        self.assertIn("Previous    : PHP   100.00", text)
        self.assertIn("Prev Penalty(10%): PHP    10.00", text)
        self.assertIn("TOTAL AMOUNT: PHP   120.00", text)
        self.assertIn("After Due   : PHP   121.00", text)

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
        due_penalty_line = "Due Penalty(10%): PHP     4.00"
        previous_line = "Previous    : PHP   360.00"
        previous_penalty_line = "Prev Penalty(10%): PHP    36.00"

        self.assertIn(current_line, text)
        self.assertIn(due_penalty_line, text)
        self.assertIn(previous_line, text)
        self.assertIn(previous_penalty_line, text)
        self.assertLess(text.index(current_line), text.index(due_penalty_line))
        self.assertLess(text.index(due_penalty_line), text.index(previous_line))
        self.assertLess(text.index(previous_line), text.index(previous_penalty_line))
        self.assertIn("TOTAL AMOUNT: PHP   436.00", text)
        self.assertIn("After Due   : PHP   440.00", text)

    def test_receipt_rolls_unpaid_amount_into_next_previous_balance(self):
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
        self.assertIn("Previous    : PHP   162.00", text)
        self.assertIn("Prev Penalty(10%): PHP    16.20", text)
        self.assertIn("TOTAL AMOUNT: PHP   208.20", text)
        self.assertIn("After Due   : PHP   211.20", text)

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
                "late_fee": None,
                "bill_status": "Unpaid",
            },
            previous=0,
            present=10,
            exception="None",
            reader_name="Reader",
        )

        self.assertIn("Due Penalty(10%): PHP    10.00", text)
        self.assertIn("After Due   : PHP   110.00", text)

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

        self.assertIn("Billing Period: 2026-07-02 to 2026-07-06", text)


if __name__ == "__main__":
    unittest.main()

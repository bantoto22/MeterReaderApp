import os
import gc
import tempfile
import threading
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import src.database as database
from src.billing_policy import late_fee_percent, payment_due_date
from src.handheld_sync import HandheldSyncDataAccess, SQLiteLocalSyncStore, SyncConfig, _build_bill_payload
from src.qt_hybrid_app import AppBridge


class BillingPolicyTests(unittest.TestCase):
    def test_weekday_and_weekend_payment_deadlines(self):
        self.assertEqual(payment_due_date("2026-09-23", 15), date(2026, 10, 8))
        self.assertEqual(payment_due_date("2026-09-24", 2), date(2026, 9, 25))
        self.assertEqual(payment_due_date("2026-09-24", 3), date(2026, 9, 28))

    def test_bill_uses_api_policy_and_never_schedule_end_date(self):
        reading = {
            "consumer_id": 8, "reading_id": "reading-8", "reading_date": "2026-09-24",
            "bill_date": "2026-09-24", "due_date": "2026-07-14",
            "schedule_due_date": "2026-09-30", "present_reading": 5,
            "previous_reading": 0, "consumption": 5,
        }
        context = {
            "minimum_cubic": 10, "minimum_rate": 100,
            "due_days": 2, "late_fee": 8, "penalty_percent": 50,
        }
        bill = _build_bill_payload(reading, context, 54, as_of_date=date(2026, 9, 26))
        self.assertEqual(bill["due_date"], "2026-09-25 00:00:00")
        self.assertEqual(bill["penalty"], 8.0)

        legacy = _build_bill_payload(reading, {**context, "due_days": None, "late_fee": None}, 54)
        self.assertEqual(legacy["due_date"], "2026-10-09 00:00:00")
        self.assertEqual(late_fee_percent(None), 10.0)

    def test_cached_api_policy_survives_offline_and_refresh_replaces_it(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as folder:
            store = SQLiteLocalSyncStore(SyncConfig())
            store._db_path = os.path.join(folder, "policy.db")
            store.ensure_schema()
            consumer = {
                "id": 8, "meter_no": "09-23-2233", "name": "Reader Test",
                "zone_name": "Zone 1", "due_days": 9, "late_fee": 6,
            }
            store.cache_consumers([consumer])
            offline = store.load_cached_consumers()[0]
            self.assertEqual((offline["due_days"], offline["late_fee"]), (9, 6))

            store.cache_consumers([{**consumer, "due_days": None, "late_fee": None}])
            unchanged = store.load_cached_consumers()[0]
            self.assertEqual((unchanged["due_days"], unchanged["late_fee"]), (9, 6))

            store.cache_consumers([{**consumer, "due_days": 20, "late_fee": 4}])
            refreshed = store.load_cached_consumers()[0]
            self.assertEqual((refreshed["due_days"], refreshed["late_fee"]), (20, 4))
            del store
            gc.collect()

    def test_ui_consumer_cache_preserves_missing_values_and_accepts_new_api_values(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as folder:
            consumer = {
                "id": 8, "meter_no": "09-23-2233", "name": "Reader Test",
                "zone_name": "Zone 1", "due_days": 9, "late_fee": 6,
            }
            with patch.object(database, "_db_path", return_value=os.path.join(folder, "ui.db")):
                database.init_db()
                database.replace_consumers_from_sync([consumer])
                database.replace_consumers_from_sync([{**consumer, "due_days": None, "late_fee": None}])
                cached = database.search_consumer("09-23-2233", unread_only=False)
                self.assertEqual((cached["due_days"], cached["late_fee"]), (9, 6))

                database.replace_consumers_from_sync([{**consumer, "due_days": 20, "late_fee": 4}])
                refreshed = database.search_consumer("09-23-2233", unread_only=False)
                self.assertEqual((refreshed["due_days"], refreshed["late_fee"]), (20, 4))
            gc.collect()

    def test_offline_sync_payload_omits_server_owned_fields(self):
        captured = []
        consumer = {
            "id": 8, "due_days": 2, "late_fee": 8,
            "penalty_percent": 50, "previous_reading": 0,
        }
        bridge = SimpleNamespace(
            _consumer=consumer, _sync_dal=SimpleNamespace(
                operation_lock=threading.RLock(), queueMeterReading=lambda payload: captured.append(payload) or {"status": "pending"},
            ),
            _selected_route=lambda: {"startDate": "2026-09-24", "dueDate": "2026-09-30"},
            _schedule_for_consumer=lambda _consumer: {"scheduleId": 549},
            selectedBillingDate="2026-09-24", _meter_reader_account_id="12",
            _auto_sync_enabled=False,
        )
        bridge._default_due_date_for_consumer = lambda source, reading_date: AppBridge._default_due_date_for_consumer(
            bridge, source, reading_date,
        )
        result = AppBridge._save_to_sync_layer(
            bridge, 8, 5, 5, "None", False,
            reading_date="2026-09-24", due_date="2026-07-14", wait_for_result=True,
        )
        self.assertEqual(result["status"], "pending")
        self.assertNotIn("due_date", captured[0])
        self.assertNotIn("penalty", captured[0])
        self.assertNotIn("previous_penalty", captured[0])
        self.assertNotIn("total_after_due_date", captured[0])
        self.assertEqual(captured[0]["billing_calculation_status"], "Pending server calculation")
        self.assertEqual(captured[0]["schedule_due_date"], "2026-09-30")
        self.assertNotIn("due_days", captured[0])
        self.assertNotIn("late_fee", captured[0])

    def test_confirmed_backend_bill_is_cached_verbatim_for_offline_context(self):
        class BillRemote:
            online = True

            def is_online(self):
                return self.online

            def save_reading_bundle(self, reading):
                return {
                    "meterreading": {"id": 54},
                    "bill": {
                        "bill_id": 99, "sync_id": reading["reading_id"],
                        "amount_due": 321.75, "penalty": 0,
                        "total_after_due_date": 321.75, "due_date": "2026-10-08",
                    },
                }

        with tempfile.TemporaryDirectory(dir=os.getcwd()) as folder:
            store = SQLiteLocalSyncStore(SyncConfig())
            store._db_path = os.path.join(folder, "confirmed.db")
            store.ensure_schema()
            store.cache_consumers([{
                "id": 8, "meter_no": "09-23-2233", "name": "Reader Test",
                "zone_name": "Zone 1", "due_days": 15, "late_fee": 8,
                "schedule_id": 549, "schedule_date": "2026-09-23",
                "schedule_due_date": "2026-09-30", "is_read": True,
            }])
            remote = BillRemote()
            dal = HandheldSyncDataAccess(store, remote)
            saved = dal.saveMeterReading({
                "consumer_id": 8, "meter_no": "09-23-2233",
                "reading_date": "2026-09-23", "present_reading": 10,
            })
            self.assertEqual(saved["status"], "synced")
            self.assertEqual(store.get_latest_confirmed_bill(8), saved["remote"]["Backend API"]["bill"])

            remote.online = False
            cached = dal.getConsumerContext(8)
            self.assertEqual(cached["amount_due"], 321.75)
            self.assertEqual(cached["due_date"], "2026-10-08")
            self.assertEqual((cached["due_days"], cached["late_fee"]), (15, 8))
            self.assertEqual(cached["is_read"], 1)
            del dal, store
            gc.collect()


if __name__ == "__main__":
    unittest.main()

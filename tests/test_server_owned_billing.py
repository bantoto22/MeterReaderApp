import gc
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import src.database as database
from src.handheld_sync import (
    BackendApiClient, HandheldSyncDataAccess, SQLiteLocalSyncStore, SyncConfig,
    _flatten_backend_bill_context,
)
from src.qt_hybrid_app import AppBridge
from src.receipt import apply_authoritative_bill, build_receipt_text


class _Remote:
    def __init__(self):
        self.online = False
        self.saved = []
        self.context = {}
        self.last_response = None

    def is_online(self):
        return self.online

    def find_existing_reading(self, consumer_id, reading_date):
        return None

    def save_reading_bundle(self, reading):
        self.saved.append(dict(reading))
        self.last_response = {
            "bill": {
                "sync_id": reading["bill_sync_id"],
                "billing_reference": reading["billing_reference"],
                "due_date": "2026-10-12", "penalty_rate": 7.5,
                "previous_penalty": 13.25, "penalty": 0,
                "amount_due": 220, "total_after_due_date": 220,
                "status": "Unpaid", "setting_id": 43, "water_charge": 200,
            },
            "billing_policy": {
                "source": "reading_schedule", "payment_due_date": "2026-10-12",
                "due_date_days": 17, "late_fee": 9,
            },
        }
        return self.last_response

    def get_consumer_context(self, consumer_id):
        return dict(self.context)


class ServerOwnedBillingTests(unittest.TestCase):
    def test_assigned_consumer_records_are_refreshed_and_available_offline(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteLocalSyncStore(SyncConfig())
            store._db_path = os.path.join(folder, "records.db")
            store.ensure_schema()
            assigned = {"id": 8, "meter_no": "09-23-2233", "name": "Test",
                        "zone_name": "Zone 1", "schedule_id": 549}
            store.cache_consumers([assigned])
            remote = _Remote()
            remote.online = True
            remote.context = {
                "consumer_id": 8, "previous_reading_date": "2026-08-20",
                "latest_reading_date": "2026-08-20",
                "readings": [{"reading_date": "2026-08-20", "present_reading": 42}],
                "payments": [{"amount": 50, "paid_at": "2026-09-01"}],
                "unpaid_bills": [{"amount_due": 120}],
                "bill": {"amount_due": 120, "due_date": "2026-09-10"},
            }
            dal = HandheldSyncDataAccess(store, remote)
            self.assertEqual(dal.prefetchAssignedConsumerContexts([assigned, assigned])["refreshed"], 1)
            remote.online = False
            cached = dal.getConsumerContext(8)
            self.assertEqual(cached["readings"][0]["present_reading"], 42)
            self.assertEqual(cached["payments"][0]["amount"], 50)
            self.assertEqual(cached["unpaid_bills"][0]["amount_due"], 120)
            self.assertEqual(cached["previous_reading_date"], "2026-08-20")
            remote.online = True
            remote.context = {**remote.context, "payments": [{"amount": 120, "paid_at": "2026-09-25"}],
                              "unpaid_bills": []}
            self.assertEqual(dal.prefetchAssignedConsumerContexts([assigned])["refreshed"], 1)
            remote.online = False
            refreshed = dal.getConsumerContext(8)
            self.assertEqual(refreshed["payments"][0]["amount"], 120)
            self.assertEqual(refreshed["unpaid_bills"], [])
            remote.online = True
            remote.get_consumer_context = Mock(side_effect=OSError("network unavailable"))
            pull = dal.prefetchAssignedConsumerContexts([assigned])
            self.assertEqual((pull["requested"], pull["refreshed"], pull["failed"]), (1, 0, 1))
            remote.online = False
            self.assertEqual(dal.getConsumerContext(8)["payments"][0]["amount"], 120)
            del dal, store
            gc.collect()

    def test_receipt_uses_server_totals_and_previous_balance(self):
        snapshot = apply_authoritative_bill(
            {"name": "Test", "meter_no": "09-23-2233", "previous_reading": 12,
             "amount_due": 0, "total_after_due_date": 0, "previous_balance": 0},
            {"total_amount": 345.75, "amount_after_due_date": 365.75,
             "Previous_Balance": 120, "previous_penalty": 12,
             "penalty": 20, "penalty_rate": 8, "water_charge": 200,
             "due_date": "2026-10-12"},
        )
        receipt = build_receipt_text(snapshot, 12, 20, "None", reading_date="2026-09-25")
        self.assertIn("TOTAL DUE      : PHP   345.75", receipt)
        self.assertIn("AFTER DUE      : PHP   365.75", receipt)
        self.assertIn("Previous       : PHP   120.00", receipt)
        self.assertIn("Prev Pen(8%)", receipt)

    def test_missing_server_totals_are_not_displayed_as_zero_or_old_bill(self):
        snapshot = apply_authoritative_bill(
            {"name": "Test", "amount_due": 500, "total_after_due_date": 550},
            {"due_date": "2026-10-12", "water_charge": 100},
        )
        receipt = build_receipt_text(snapshot, 0, 4, "None", reading_date="2026-09-25")
        self.assertIn("TOTAL DUE", receipt)
        self.assertIn("Pending server\n                  calculation", receipt)
        self.assertNotIn("PHP   500.00", receipt)
        self.assertNotIn("PHP   550.00", receipt)

    def test_nested_bill_aliases_override_old_context_totals(self):
        context = _flatten_backend_bill_context({
            "amount_due": 0, "previous_balance": 0, "total_after_due_date": 0,
            "bill": {"total_amount": 345.75, "Previous_Balance": 120,
                     "amount_after_due_date": 365.75},
        })
        self.assertEqual(context["amount_due"], 345.75)
        self.assertEqual(context["previous_balance"], 120)
        self.assertEqual(context["total_after_due_date"], 365.75)

    def test_partial_assignment_refresh_preserves_confirmed_bill_amounts(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteLocalSyncStore(SyncConfig())
            store._db_path = os.path.join(folder, "queue.db")
            store.ensure_schema()
            base = {"id": 8, "meter_no": "09-23-2233", "name": "Test"}
            store.cache_consumers([{**base, "amount_due": 345.75,
                                    "previous_balance": 120, "previous_penalty": 12,
                                    "total_after_due_date": 365.75, "penalty": 20}])
            store.cache_consumers([base])
            cached = store.load_cached_consumers()[0]
            self.assertEqual(cached["amount_due"], 345.75)
            self.assertEqual(cached["previous_balance"], 120)
            self.assertEqual(cached["previous_penalty"], 12)
            self.assertEqual(cached["total_after_due_date"], 365.75)
            self.assertEqual(cached["penalty"], 20)
            del store
            gc.collect()

    def test_ui_consumer_refresh_keeps_server_bill_amounts(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(database, "_db_path", return_value=os.path.join(folder, "ui.db")):
                database.init_db()
                base = {"id": 8, "meter_no": "09-23-2233", "name": "Test",
                        "zone_name": "Zone 1"}
                database.replace_consumers_from_sync([{
                    **base, "amount_due": 345.75, "previous_balance": 120,
                    "previous_penalty": 12, "total_after_due_date": 365.75,
                }])
                database.replace_consumers_from_sync([base])
                conn = database.get_connection()
                try:
                    row = conn.execute(
                        "SELECT amount_due, previous_balance, previous_penalty, "
                        "total_after_due_date FROM consumers WHERE id=8"
                    ).fetchone()
                    self.assertEqual(tuple(row), (345.75, 120, 12, 365.75))
                finally:
                    conn.close()
            gc.collect()

    def test_post_contains_base_charges_but_no_final_bill_fields(self):
        client = BackendApiClient(SyncConfig(backend_api_base_url="https://example.test"))
        calls = []
        bill_id = "550e8400-e29b-41d4-a716-446655440000"

        def request(method, path, *, payload=None, query=None):
            calls.append((method, path, payload))
            return 200, {"bill": {"sync_id": bill_id, "billing_reference": "SLR2026000125"}}

        client._req = request
        client.save_reading_bundle({
            "consumer_id": 8, "reading_id": "reading-8", "reading_date": "2026-09-25",
            "previous_reading": 2, "present_reading": 5, "consumption": 3,
            "minimum_cubic": 10, "minimum_rate": 100, "excess_rate_per_cubic": 15,
            "water_meter_fee": 3, "connection_fee": 2, "membership_fee": 1,
            "bill_sync_id": bill_id, "bill_date": "2026-09-25",
            "billing_reference": "SLR2026000125",
            "schedule_due_date": "2026-09-30",
            "schedule_payment_due_date": "2026-10-12", "due_date": "2026-07-14",
            "penalty": 50, "previous_penalty": 10, "total_after_due_date": 200,
            "status": "Unpaid", "setting_id": 9,
            "due_days": 15, "late_fee": 10, "amount_due": 100,
        })
        method, path, payload = calls[0]
        self.assertEqual((method, path), ("POST", "/api/handheld/reading-bundles"))
        self.assertEqual(payload["bill"]["water_charge"], 100)
        self.assertEqual(payload["bill"]["meter_maintenance_fee"], 3)
        self.assertEqual(payload["reading"]["schedule_due_date"], "2026-09-30")
        self.assertEqual(payload["reading"]["schedule_payment_due_date"], "2026-10-12")
        for section in ("reading", "bill"):
            for field in ("due_date", "previous_penalty", "penalty", "total_after_due_date", "status", "setting_id", "due_days", "late_fee", "amount_due"):
                self.assertNotIn(field, payload[section])

    def test_offline_pending_then_reconnect_keeps_exact_server_bill_and_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteLocalSyncStore(SyncConfig())
            store._db_path = os.path.join(folder, "queue.db")
            store.ensure_schema()
            consumer = {
                "id": 8, "meter_no": "09-23-2233", "name": "Test", "zone_name": "Zone 1",
                "schedule_id": 549, "schedule_date": "2026-09-25",
                "schedule_due_date": "2026-09-30",
                "schedule_payment_due_date": "2026-10-12",
            }
            store.cache_consumers([consumer])
            remote = _Remote()
            dal = HandheldSyncDataAccess(store, remote)
            saved = dal.saveMeterReading({
                "consumer_id": 8, "meter_no": "09-23-2233", "reading_date": "2026-09-25",
                "present_reading": 5, "consumption": 3,
                "bill_sync_id": "550e8400-e29b-41d4-a716-446655440000",
                "billing_reference": "SLR2026000125", "bill_date": "2026-09-25",
                "schedule_due_date": "2026-09-30",
                "schedule_payment_due_date": "2026-10-12",
                "due_date": "2026-07-14", "penalty": 30,
            })
            self.assertEqual(saved["status"], "queued")
            self.assertEqual(saved["reading"]["billing_calculation_status"], "Pending server calculation")
            self.assertNotIn("due_date", saved["reading"])
            self.assertNotIn("penalty", saved["reading"])
            self.assertEqual(saved["reading"]["schedule_payment_due_date"], "2026-10-12")
            self.assertEqual(store.get_latest_confirmed_bill(8), {})

            remote.online = True
            result = dal.syncPendingReadings()
            self.assertEqual(result["synced"], 1)
            exact_bill = remote.last_response["bill"]
            self.assertEqual(store.get_latest_confirmed_bill(8), exact_bill)
            remote.online = False
            cached = dal.getConsumerContext(8)
            self.assertEqual(cached["due_date"], "2026-10-12")
            self.assertEqual(cached["penalty_rate"], 7.5)
            self.assertEqual(cached["previous_penalty"], 13.25)
            self.assertEqual(cached["setting_id"], 43)
            self.assertEqual(cached["billing_policy_source"], "reading_schedule")
            self.assertEqual(cached["billing_policy_payment_due_date"], "2026-10-12")
            self.assertEqual(cached["schedule_due_date"], "2026-09-30")
            self.assertEqual(cached["schedule_payment_due_date"], "2026-10-12")
            self.assertEqual((cached["due_days"], cached["late_fee"]), (17, 9))
            store.cache_consumers([{**consumer, "schedule_payment_due_date": "2026-10-20"}])
            self.assertEqual(dal.getConsumerContext(8)["due_date"], "2026-10-12")
            self.assertEqual(dal.getConsumerContext(8)["schedule_payment_due_date"], "2026-10-20")
            self.assertEqual(store.get_latest_confirmed_bill(8), exact_bill)
            remote.online = True
            remote.context = {
                "consumer_id": 8,
                "billing_policy": {
                    "source": "reading_schedule", "payment_due_date": "2026-10-20",
                    "due_date_days": 20, "late_fee": 12,
                },
                "bill": {**exact_bill, "penalty": 16.5, "total_after_due_date": 236.5},
            }
            refreshed = dal.getConsumerContext(8)
            self.assertEqual(refreshed["penalty"], 16.5)
            self.assertEqual(refreshed["penalty_rate"], 7.5)
            self.assertEqual(refreshed["due_date"], "2026-10-12")
            self.assertEqual(refreshed["billing_policy_payment_due_date"], "2026-10-20")
            self.assertEqual((refreshed["due_days"], refreshed["late_fee"]), (20, 12))
            remote.online = False
            self.assertEqual(dal.getConsumerContext(8)["total_after_due_date"], 236.5)
            self.assertEqual(len(remote.saved), 1)
            del dal, store
            gc.collect()

    def test_schedule_list_date_survives_offline_and_refreshes_without_bill_math(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteLocalSyncStore(SyncConfig())
            store._db_path = os.path.join(folder, "assignments.db")
            store.ensure_schema()
            schedule = {
                "schedule_id": 549, "start_date": "2026-09-25",
                "due_date": "2026-09-30", "payment_due_date": "2026-10-12",
                "zone_name": "Zone 1", "meter_reader_id": 12,
            }
            store.cache_reading_schedules([schedule], 12, None, None)
            store.cache_consumers([{
                "id": 8, "meter_no": "09-23-2233", "name": "Test",
                "zone_name": "Zone 1", "schedule_id": 549,
                "schedule_due_date": "2026-09-30", "due_days": 15,
                "schedule_payment_due_date": "2026-10-12",
            }])
            cached = store.load_cached_consumers()[0]
            self.assertEqual(cached["schedule_payment_due_date"], "2026-10-12")
            self.assertEqual(cached["schedule_due_date"], "2026-09-30")
            self.assertIsNone(cached["due_date"])
            store.cache_reading_schedules(
                [{**schedule, "payment_due_date": "2026-10-20"}], 12, None, None,
            )
            self.assertEqual(store.load_cached_consumers()[0]["schedule_payment_due_date"], "2026-10-20")
            store.cache_consumers([{
                "id": 8, "meter_no": "09-23-2233", "name": "Test",
                "zone_name": "Zone 1", "schedule_id": 549,
                "schedule_payment_due_date": "2026-10-12",
            }])
            self.assertEqual(store.load_cached_consumers()[0]["schedule_payment_due_date"], "2026-10-20")
            del store
            gc.collect()

    def test_policy_payment_date_is_diagnostic_not_a_bill_due_date(self):
        context = _flatten_backend_bill_context({
            "consumer_id": 8,
            "schedule_due_date": "2026-09-30",
            "reading_schedule": {"payment_due_date": "2026-10-12"},
            "billing_policy": {
                "source": "reading_schedule", "payment_due_date": "2026-10-12",
                "due_date_days": 15, "late_fee": 9,
            },
        })
        self.assertEqual(context["billing_policy_payment_due_date"], "2026-10-12")
        self.assertEqual(context["billing_policy_source"], "reading_schedule")
        self.assertEqual(context["schedule_payment_due_date"], "2026-10-12")
        self.assertNotIn("due_date", context)

    def test_schedule_payment_date_is_cached_separately_from_end_date(self):
        schedule = {
            "schedule_id": 549, "start_date": "2026-09-25", "due_date": "2026-09-30",
            "payment_due_date": "2026-10-12", "zone_name": "Zone 1",
            "meter_reader_id": 12, "status": "Scheduled",
        }
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(database, "_db_path", return_value=os.path.join(folder, "ui.db")):
                database.init_db()
                database.replace_reading_schedules_from_sync([schedule], 12, None, None)
                database.replace_consumers_from_sync([{
                    "id": 8, "meter_no": "09-23-2233", "name": "Test",
                    "zone_name": "Zone 1", "schedule_id": 549,
                }])
                row = database.search_consumer(
                    "09-23-2233", unread_only=False, schedule_date="2026-09-25",
                    meter_reader_id=12, schedule_id=549,
                )
                self.assertEqual(row["schedule_due_date"], "2026-09-30")
                self.assertEqual(row["schedule_payment_due_date"], "2026-10-12")
                self.assertIsNone(row["due_date"])
                database.replace_reading_schedules_from_sync(
                    [{**schedule, "payment_due_date": "2026-10-20"}], 12, None, None,
                )
                refreshed = database.search_consumer(
                    "09-23-2233", unread_only=False, schedule_date="2026-09-25",
                    meter_reader_id=12, schedule_id=549,
                )
                self.assertEqual(refreshed["schedule_payment_due_date"], "2026-10-20")
                database.replace_consumers_from_sync([{
                    "id": 8, "meter_no": "09-23-2233", "name": "Test",
                    "zone_name": "Zone 1", "schedule_id": 549,
                    "schedule_payment_due_date": "2026-10-12",
                }])
                refreshed = database.search_consumer(
                    "09-23-2233", unread_only=False, schedule_date="2026-09-25",
                    meter_reader_id=12, schedule_id=549,
                )
                self.assertEqual(refreshed["schedule_payment_due_date"], "2026-10-20")
                self.assertIsNone(refreshed["due_date"])
                self.assertEqual(AppBridge._default_due_date_for_consumer(
                    SimpleNamespace(_consumer={}),
                    {"schedule_id": 549, "schedule_payment_due_date": "2026-10-12"},
                ), "2026-10-20")
            gc.collect()

    def test_unissued_form_does_not_calculate_fallback_date(self):
        bridge = SimpleNamespace(_consumer={})
        self.assertEqual(AppBridge._default_due_date_for_consumer(
            bridge, {"due_days": 15, "schedule_due_date": "2026-09-30"}, "2026-09-25",
        ), "")
        self.assertEqual(AppBridge._default_due_date_for_consumer(
            bridge, {"schedule_payment_due_date": "2026-10-12"}, "2026-09-25",
        ), "2026-10-12")

    def test_context_refresh_displays_saved_penalty_and_captured_rate(self):
        reference = "SLR2026000125"
        entry = {
            "consumer_id": 8, "acct_no": "04-11-123", "consumer_name": "Reader Test",
            "name": "Reader Test", "meter_no": "09-23-2233",
            "previous_reading": 2, "present_reading": 5, "exception": "None",
            "receipt_text": f"Billing Ref    : {reference}\nDate           : 2026-09-25",
        }
        context = {
            "id": 8, "billing_reference": reference, "minimum_cubic": 10,
            "minimum_rate": 100, "excess_rate_per_cubic": 15,
            "late_fee": 25, "bill": {
                "billing_reference": reference, "due_date": "2026-10-12",
                "penalty_rate": 7.5, "amount_due": 220, "water_charge": 200,
                "previous_balance": 120, "previous_penalty": 13.25,
                "penalty": 15, "total_after_due_date": 235,
                "status": "Unpaid", "setting_id": 43,
            },
        }
        bridge = SimpleNamespace(
            _sync_dal=SimpleNamespace(is_online=lambda: True, getConsumerContext=lambda _id: context),
            _reader_name="Juan Dela Cruz",
        )
        with patch("src.qt_hybrid_app.build_receipt_text", wraps=__import__("src.receipt", fromlist=["build_receipt_text"]).build_receipt_text) as render:
            receipt = AppBridge._refresh_saved_receipt_penalty(bridge, entry)
        self.assertTrue(render.called)
        self.assertIn("Due Pen(7.5%)", receipt)
        self.assertIn("PHP    15.00", receipt)
        self.assertIn("AFTER DUE      : PHP   235.00", receipt)
        self.assertIn("Previous       : PHP   120.00", receipt)
        self.assertIn("2026-10-12", receipt)

    def test_pending_reading_cannot_print_a_previous_bill(self):
        alerts = Mock()
        bridge = SimpleNamespace(
            _selected_route_consumer_rows=lambda: [{
                "id": 8, "is_read": True, "reading_value": 5,
                "consumption": 3, "reading_date": "2026-09-25",
            }],
            _sync_dal=SimpleNamespace(getConsumerContext=lambda _id: {
                "bill": {"billing_reference": "SLR2026000125", "bill_date": "2026-08-25", "due_date": "2026-09-10"},
            }),
            alertRequested=SimpleNamespace(emit=alerts),
        )
        with patch("src.qt_hybrid_app.get_latest_receipt_print", return_value=None), patch(
            "src.qt_hybrid_app.build_receipt_text"
        ) as render:
            AppBridge.reprintZoneConsumer(bridge, 8)
        render.assert_not_called()
        self.assertEqual(alerts.call_args.args[0], "Pending server calculation")


if __name__ == "__main__":
    unittest.main()

import gc
import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import src.database as database
from src.handheld_sync import (
    BackendApiClient, HandheldSyncDataAccess, SQLiteLocalSyncStore, SyncConfig,
    _flatten_backend_bill_context,
)
from src.qt_hybrid_app import (
    AppBridge, _cached_bill_for_reading, _display_consumer_context,
    _use_local_bill_for_display,
)
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
    def test_local_bill_from_device_survives_restart_and_fills_incomplete_server_bill(self):
        local_bill = {
            "sync_id": "bill-8", "consumer_id": 8, "schedule_id": 549,
            "bill_date": "2026-09-25 00:00:00", "due_date": "2026-10-12 00:00:00",
            "billing_reference": "SLR2026000125", "water_charge": 100,
            "amount_due": 150, "total_after_due_date": 165,
            "previous_balance": 50, "previous_penalty": 0,
        }
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "local-bills.db")
            store = SQLiteLocalSyncStore(SyncConfig())
            store._db_path = path
            store.ensure_schema()
            dal = HandheldSyncDataAccess(store, None)
            dal.cacheLocalBill(8, local_bill)
            reopened = SQLiteLocalSyncStore(SyncConfig())
            reopened._db_path = path
            reopened.ensure_schema()
            reopened.cache_consumer_context(8, {"bill": {
                "sync_id": "bill-8", "bill_date": "2026-09-25",
                "billing_reference": "SLR2026000125", "due_date": "2026-10-12",
                "amount_due": 0, "total_after_due_date": 0, "status": "Unpaid",
            }})
            saved = reopened.load_cached_consumer_context(8)
            reading = {"reading_date": "2026-09-25", "schedule_id": 549}
            self.assertEqual(_cached_bill_for_reading(saved, reading), local_bill)
            self.assertEqual(saved["local_bills"], [local_bill])
            reopened.cache_consumer_context(8, {"bill": {
                **saved["bill"], "amount_due": 148,
                "total_after_due_date": 163, "water_charge": 98,
            }})
            self.assertEqual(_cached_bill_for_reading(
                reopened.load_cached_consumer_context(8), reading,
            )["amount_due"], 148)
            del dal, store, reopened
            gc.collect()

    def test_next_offline_bill_carries_saved_local_bill_when_server_total_is_zero(self):
        from src.handheld_sync import _build_bill_payload

        bill = _build_bill_payload(
            {"reading_id": "reading-new", "bill_sync_id": "bill-new",
             "consumer_id": 8, "previous_reading": 5, "present_reading": 7,
             "consumption": 2, "reading_date": "2026-10-20",
             "schedule_payment_due_date": "2026-11-04"},
            {"minimum_cubic": 10, "minimum_rate": 100,
             "excess_rate_per_cubic": 15, "late_fee": 10,
             "amount_due": 0, "bill_status": "Unpaid",
             "local_bill": {"sync_id": "bill-old", "bill_date": "2026-09-25",
                            "due_date": "2026-10-12", "water_charge": 100,
                            "amount_due": 150, "previous_penalty": 0,
                            "penalty_rate": 5, "status": "Unpaid"},
             "bill": {"sync_id": "bill-old", "amount_due": 0, "status": "Unpaid"}},
            0, as_of_date=date(2026, 10, 20),
        )
        self.assertEqual(bill["previous_balance"], 150)
        self.assertEqual(bill["previous_penalty"], 5)
        self.assertEqual(bill["amount_due"], 255)
        self.assertEqual(bill["due_date"], "2026-11-04 00:00:00")

    def test_cached_previous_balance_survives_zero_assignment_totals(self):
        from src.handheld_sync import _build_bill_payload

        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteLocalSyncStore(SyncConfig())
            store._db_path = os.path.join(folder, "previous-bill.db")
            store.ensure_schema()
            assignment = {
                "id": 8, "meter_no": "09-23-2233", "name": "Test",
                "zone_name": "Zone 1", "minimum_cubic": 10,
                "minimum_rate": 100, "excess_rate_per_cubic": 15,
                "amount_due": 0, "previous_balance": 0,
                "previous_penalty": 0, "bill_status": "Unpaid",
            }
            store.cache_consumers([assignment])
            store.cache_consumer_context(8, {
                "amount_due": 0, "previous_balance": 145,
                "previous_penalty": 10, "bill_status": "Unpaid",
            })
            store.cache_consumers([assignment])
            dal = HandheldSyncDataAccess(store, None)
            context = dal.getCachedConsumerContext(8)
            self.assertEqual(context["previous_balance"], 145)
            self.assertEqual(context["previous_penalty"], 10)
            reading = {
                "consumer_id": 8, "previous_reading": 5,
                "present_reading": 7, "consumption": 2,
                "reading_date": "2026-09-25",
                "schedule_payment_due_date": "2026-10-12",
            }
            bill = _build_bill_payload(reading, context, 0, as_of_date=date(2026, 9, 25))
            self.assertEqual(bill["previous_balance"], 145)
            self.assertEqual(bill["previous_penalty"], 10)
            self.assertEqual(bill["amount_due"], 255)
            store.cache_consumer_context(8, {"bill_status": "Paid"})
            paid = _build_bill_payload(
                reading, dal.getCachedConsumerContext(8), 0,
                as_of_date=date(2026, 9, 25),
            )
            self.assertEqual(paid["previous_balance"], 0)
            self.assertEqual(paid["amount_due"], 100)
            del dal, store
            gc.collect()

    def test_previous_bill_label_uses_balance_even_with_zero_previous_meter_reading(self):
        receipt = build_receipt_text(
            apply_authoritative_bill({
                "minimum_cubic": 10, "minimum_rate": 100,
                "excess_rate_per_cubic": 15,
            }, {
                "water_charge": 100, "previous_balance": 145,
                "previous_penalty": 10, "amount_due": 255,
                "total_after_due_date": 255, "penalty": 0,
                "due_date": "2026-10-12", "status": "Unpaid",
            }),
            0, 2, "None", reading_date="2026-09-25",
        )
        self.assertIn("Prev Bill      : PHP 145.00", receipt)
        self.assertIn("Previous       : PHP   145.00", receipt)

    def test_reconnect_refreshes_assignments_without_pending_uploads(self):
        view = SimpleNamespace(
            _wifi_status="Status: Offline", _wifi_status_color="gray",
            _auto_sync_enabled=True,
            wifiStatusChanged=SimpleNamespace(emit=Mock()),
            wifiStatusColorChanged=SimpleNamespace(emit=Mock()),
            _start_heartbeat=Mock(), _start_reconnect_sync=Mock(),
            _start_assigned_consumer_dataset_refresh=Mock(),
        )
        AppBridge._set_wifi_status(view, "Status: Connected to Wi-Fi", "green")
        view._start_assigned_consumer_dataset_refresh.assert_called_once_with()

    def test_local_receipt_fills_missing_or_zero_unpaid_server_totals(self):
        local = {"amount_due": 150, "total_after_due_date": 165}
        self.assertTrue(_use_local_bill_for_display(None, local))
        self.assertTrue(_use_local_bill_for_display(
            {"amount_due": 0, "total_after_due_date": 0, "status": "Unpaid"}, local,
        ))
        self.assertFalse(_use_local_bill_for_display(
            {"amount_due": 150, "total_after_due_date": 165, "status": "Unpaid"}, local,
        ))
        self.assertFalse(_use_local_bill_for_display(
            {"amount_due": 0, "total_after_due_date": 0, "status": "Paid"}, local,
        ))

    def test_display_uses_cached_context_without_network(self):
        dal = SimpleNamespace(
            getCachedConsumerContext=Mock(return_value={"amount_due": 120}),
            getConsumerContext=Mock(side_effect=AssertionError("network request")),
        )
        self.assertEqual(_display_consumer_context(dal, 8)["amount_due"], 120)
        dal.getCachedConsumerContext.assert_called_once_with(8)
        dal.getConsumerContext.assert_not_called()

    def test_reprint_keeps_local_amount_when_unpaid_server_bill_is_zero(self):
        entry = {
            "consumer_id": 8,
            "receipt_text": "Billing Ref    : SLR2026000125\nTOTAL DUE      : PHP   150.00",
        }
        bridge = SimpleNamespace(
            _sync_dal=SimpleNamespace(getCachedConsumerContext=lambda _id: {
                "billing_reference": "SLR2026000125",
                "bill": {"billing_reference": "SLR2026000125", "amount_due": 0,
                         "total_after_due_date": 0, "status": "Unpaid"},
            }),
            _reader_name="Juan Dela Cruz",
        )
        self.assertEqual(AppBridge._refresh_saved_receipt_penalty(bridge, entry), entry["receipt_text"])

    def test_context_history_keeps_newest_fifteen_across_restarts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "history.db")
            store = SQLiteLocalSyncStore(SyncConfig())
            store._db_path = path
            store.ensure_schema()
            store.cache_consumer_context(8, {"payments": [
                {"id": number, "payment_date": f"2026-09-{number:02d}", "amount": number}
                for number in range(1, 17)
            ], "unpaid_bills": [{"id": 1}],
                "account_records": {"adjustments": [{"id": 7, "amount": 3,
                                                      "access_token": "private"}]},
                "session_token": "must-not-be-cached"})
            reopened = SQLiteLocalSyncStore(SyncConfig())
            reopened._db_path = path
            reopened.ensure_schema()
            saved = reopened.load_cached_consumer_context(8)
            self.assertEqual([row["id"] for row in saved["payments"]], list(range(2, 17)))
            self.assertEqual(saved["account_records"]["adjustments"][0]["amount"], 3)
            self.assertNotIn("access_token", saved["account_records"]["adjustments"][0])
            self.assertNotIn("session_token", saved)
            reopened.cache_consumer_context(8, {
                "payments": [{"id": 17, "payment_date": "2026-09-17", "amount": 17}],
                "unpaid_bills": [],
            })
            saved = reopened.load_cached_consumer_context(8)
            self.assertEqual([row["id"] for row in saved["payments"]], list(range(3, 18)))
            self.assertEqual(saved["unpaid_bills"], [])
            del store, reopened
            gc.collect()

    def test_assignment_refresh_keeps_cached_rates_across_restarts(self):
        base = {"id": 8, "meter_no": "09-23-2233", "name": "Test", "zone_name": "Zone 1"}
        rates = {"previous_reading": 42, "minimum_cubic": 10, "minimum_rate": 100,
                 "excess_rate_per_cubic": 12, "water_meter_fee": 5,
                 "connection_fee": 3, "membership_fee": 2}
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteLocalSyncStore(SyncConfig())
            store._db_path = os.path.join(folder, "sync.db")
            store.ensure_schema()
            store.cache_consumers([{**base, **rates}])
            reopened = SQLiteLocalSyncStore(SyncConfig())
            reopened._db_path = store._db_path
            reopened.ensure_schema()
            reopened.cache_consumers([base])
            cached = reopened.load_cached_consumers()[0]
            self.assertTrue(all(cached[field] == value for field, value in rates.items()))
            reopened.cache_consumers([{**base, "minimum_rate": 120, "water_meter_fee": 0}])
            cached = reopened.load_cached_consumers()[0]
            self.assertEqual((cached["minimum_rate"], cached["water_meter_fee"]), (120, 0))
            with patch.object(database, "_db_path", return_value=os.path.join(folder, "ui.db")):
                database.init_db()
                database.replace_consumers_from_sync([{**base, **rates}])
                database.replace_consumers_from_sync([base])
                conn = database.get_connection()
                try:
                    row = conn.execute(
                        "SELECT previous_reading, minimum_cubic, minimum_rate, excess_rate_per_cubic, "
                        "water_meter_fee, connection_fee, membership_fee "
                        "FROM consumers WHERE id=8"
                    ).fetchone()
                    self.assertEqual(tuple(row), tuple(rates.values()))
                finally:
                    conn.close()
                database.replace_consumers_from_sync([{**base, "minimum_rate": 120,
                                                       "water_meter_fee": 0}])
                conn = database.get_connection()
                try:
                    row = conn.execute(
                        "SELECT minimum_rate, water_meter_fee FROM consumers WHERE id=8"
                    ).fetchone()
                    self.assertEqual(tuple(row), (120, 0))
                finally:
                    conn.close()
            del store, reopened
            gc.collect()

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
            self.assertEqual([row["amount"] for row in refreshed["payments"]], [50, 120])
            self.assertEqual(refreshed["unpaid_bills"], [])
            remote.online = True
            remote.get_consumer_context = Mock(side_effect=OSError("network unavailable"))
            pull = dal.prefetchAssignedConsumerContexts([assigned])
            self.assertEqual((pull["requested"], pull["refreshed"], pull["failed"]), (1, 0, 1))
            remote.online = False
            self.assertEqual(dal.getConsumerContext(8)["payments"][-1]["amount"], 120)
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

    def test_unissued_form_calculates_fallback_payment_date(self):
        bridge = SimpleNamespace(_consumer={})
        self.assertEqual(AppBridge._default_due_date_for_consumer(
            bridge, {"due_days": 15, "schedule_due_date": "2026-09-30"}, "2026-09-25",
        ), "2026-10-09")
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

    def test_reading_cannot_print_a_previous_bill(self):
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
        self.assertEqual(alerts.call_args.args[0], "Bill Unavailable")

    def test_saved_local_bill_can_be_reprinted_without_server_or_print_history(self):
        alerts = Mock()
        preview = Mock()
        bridge = SimpleNamespace(
            _selected_route_consumer_rows=lambda: [{
                "id": 8, "is_read": True, "reading_value": 5,
                "consumption": 3, "reading_date": "2026-09-25", "schedule_id": 549,
            }],
            _sync_dal=SimpleNamespace(getCachedConsumerContext=lambda _id: {
                "local_bill": {
                    "sync_id": "bill-8", "schedule_id": 549,
                    "billing_reference": "SLR2026000125",
                    "bill_date": "2026-09-25", "due_date": "2026-10-12",
                    "water_charge": 100, "amount_due": 150,
                    "total_after_due_date": 165,
                },
                "minimum_cubic": 10, "minimum_rate": 100,
                "excess_rate_per_cubic": 15,
            }),
            _reader_name="Juan Dela Cruz", _selected_zone="Zone 1",
            alertRequested=SimpleNamespace(emit=alerts),
            canReprintChanged=SimpleNamespace(emit=Mock()),
            receiptPreviewRequested=SimpleNamespace(emit=preview),
        )
        with patch("src.qt_hybrid_app.get_latest_receipt_print", return_value=None), patch(
            "src.qt_hybrid_app.can_use_system_printer", return_value=False,
        ), patch("src.qt_hybrid_app.save_receipt_print", return_value=1):
            AppBridge.reprintZoneConsumer(bridge, 8)
        alerts.assert_not_called()
        self.assertIn("TOTAL DUE      : PHP   150.00", preview.call_args.args[1])
        self.assertIn("Due Date       : 2026-10-12", preview.call_args.args[1])


if __name__ == "__main__":
    unittest.main()

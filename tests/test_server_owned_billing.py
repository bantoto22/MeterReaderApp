import gc
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.handheld_sync import BackendApiClient, HandheldSyncDataAccess, SQLiteLocalSyncStore, SyncConfig
from src.qt_hybrid_app import AppBridge


class _Remote:
    def __init__(self):
        self.online = False
        self.saved = []
        self.context = {}

    def is_online(self):
        return self.online

    def find_existing_reading(self, consumer_id, reading_date):
        return None

    def save_reading_bundle(self, reading):
        self.saved.append(dict(reading))
        return {
            "bill": {
                "sync_id": reading["bill_sync_id"],
                "billing_reference": reading["billing_reference"],
                "due_date": "2026-10-12", "penalty_rate": 7.5,
                "previous_penalty": 13.25, "penalty": 0,
                "amount_due": 220, "total_after_due_date": 220,
                "status": "Unpaid", "setting_id": 43, "water_charge": 200,
            },
            "billing_policy": {"source": "admin_settings", "due_date_days": 17, "late_fee": 9},
        }

    def get_consumer_context(self, consumer_id):
        return dict(self.context)


class ServerOwnedBillingTests(unittest.TestCase):
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
            "schedule_due_date": "2026-09-30", "due_date": "2026-07-14",
            "penalty": 50, "previous_penalty": 10, "total_after_due_date": 200,
            "status": "Unpaid", "setting_id": 9,
            "due_days": 15, "late_fee": 10, "amount_due": 100,
        })
        method, path, payload = calls[0]
        self.assertEqual((method, path), ("POST", "/api/handheld/reading-bundles"))
        self.assertEqual(payload["bill"]["water_charge"], 100)
        self.assertEqual(payload["bill"]["meter_maintenance_fee"], 3)
        self.assertEqual(payload["reading"]["schedule_due_date"], "2026-09-30")
        for section in ("reading", "bill"):
            for field in ("due_date", "previous_penalty", "penalty", "total_after_due_date", "status", "setting_id", "due_days", "late_fee", "amount_due"):
                self.assertNotIn(field, payload[section])

    def test_offline_pending_then_reconnect_keeps_exact_server_bill_and_policy(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as folder:
            store = SQLiteLocalSyncStore(SyncConfig())
            store._db_path = os.path.join(folder, "queue.db")
            store.ensure_schema()
            store.cache_consumers([{"id": 8, "meter_no": "09-23-2233", "name": "Test", "zone_name": "Zone 1"}])
            remote = _Remote()
            dal = HandheldSyncDataAccess(store, remote)
            saved = dal.saveMeterReading({
                "consumer_id": 8, "meter_no": "09-23-2233", "reading_date": "2026-09-25",
                "present_reading": 5, "consumption": 3,
                "bill_sync_id": "550e8400-e29b-41d4-a716-446655440000",
                "billing_reference": "SLR2026000125", "bill_date": "2026-09-25",
                "due_date": "2026-07-14", "penalty": 30,
            })
            self.assertEqual(saved["status"], "queued")
            self.assertEqual(saved["reading"]["billing_calculation_status"], "Pending server calculation")
            self.assertNotIn("due_date", saved["reading"])
            self.assertNotIn("penalty", saved["reading"])
            self.assertEqual(store.get_latest_confirmed_bill(8), {})

            remote.online = True
            result = dal.syncPendingReadings()
            self.assertEqual(result["synced"], 1)
            exact_bill = remote.save_reading_bundle(remote.saved[0])["bill"]
            self.assertEqual(store.get_latest_confirmed_bill(8), exact_bill)
            remote.online = False
            cached = dal.getConsumerContext(8)
            self.assertEqual(cached["due_date"], "2026-10-12")
            self.assertEqual(cached["penalty_rate"], 7.5)
            self.assertEqual(cached["previous_penalty"], 13.25)
            self.assertEqual(cached["setting_id"], 43)
            self.assertEqual(cached["billing_policy_source"], "admin_settings")
            self.assertEqual((cached["due_days"], cached["late_fee"]), (17, 9))
            remote.online = True
            remote.context = {"consumer_id": 8, "bill": {
                **exact_bill, "penalty": 16.5, "total_after_due_date": 236.5,
            }}
            refreshed = dal.getConsumerContext(8)
            self.assertEqual(refreshed["penalty"], 16.5)
            self.assertEqual(refreshed["penalty_rate"], 7.5)
            remote.online = False
            self.assertEqual(dal.getConsumerContext(8)["total_after_due_date"], 236.5)
            del dal, store
            gc.collect()

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
                "previous_balance": 0, "previous_penalty": 13.25,
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

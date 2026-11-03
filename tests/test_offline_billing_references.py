import gc
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.handheld_sync import BackendApiClient, HandheldSyncDataAccess, SQLiteLocalSyncStore, SyncConfig
from src.qt_hybrid_app import AppBridge, _receipt_billing_reference
from src.receipt import send_to_system_printer


class ReservationBackend(BackendApiClient):
    def __init__(self):
        super().__init__(SyncConfig(backend_api_base_url="https://backend.example.test", device_id="TEST-DEVICE"))
        self.online = True
        self.reservations = {}
        self.calls = []
        self.saved = []
        self.lose_response = False
        self.wrong_response_reference = False

    def is_online(self):
        return self.online

    def reserve_billing_reference(self, bill_sync_id, bill_date):
        if not self.online:
            raise AssertionError("Offline printing must not request a reference")
        self.calls.append((bill_sync_id, bill_date))
        if bill_sync_id not in self.reservations:
            self.reservations[bill_sync_id] = {
                "bill_date": bill_date,
                "billing_reference": f"SLR{bill_date[:4]}{len(self.reservations) + 1:06d}",
            }
        result = self.reservations[bill_sync_id]
        if self.lose_response:
            self.lose_response = False
            raise RuntimeError("Connection lost after reserving the number")
        return dict(result)

    def find_existing_reading(self, consumer_id, reading_date):
        return None

    def _req(self, method, path, *, payload=None, **kwargs):
        if (method, path) != ("POST", "/api/handheld/reading-bundles"):
            raise AssertionError(f"Unexpected API call: {method} {path}")
        bill = payload["bill"]
        reserved = self.reservations[bill["sync_id"]]
        if (reserved["bill_date"] != bill["bill_date"]
                or reserved["billing_reference"] != bill["billing_reference"]):
            raise ValueError("The uploaded bill changed its reserved reference or date")
        self.saved.append({**payload["reading"], **bill, "bill_sync_id": bill["sync_id"]})
        response_bill = {**reserved, "sync_id": bill["sync_id"],
                         "consumer_id": payload["reading"]["consumer_id"], "due_date": "2027-01-15",
                         "amount_due": 100, "total_after_due_date": 110, "water_charge": 100}
        if self.wrong_response_reference:
            response_bill["billing_reference"] = "SLR2027999999"
        return 200, {"bill": response_bill}


class InlineThread:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class OfflineBillingReferenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name) / "references.db")
        self.addCleanup(gc.collect)
        self.remote = ReservationBackend()
        self.dal = self.reopen()
        self.consumer = {
            "id": 8, "consumer_id": 8, "name": "Test Consumer", "acct_no": "ACCT-8",
            "meter_no": "MTR-8", "schedule_id": 401, "schedule_date": "2026-12-31",
            "schedule_due_date": "2027-01-02", "billing_cycle": "January 2027",
            "minimum_cubic": 10, "minimum_rate": 100, "excess_rate_per_cubic": 15,
            "previous_reading": 5, "previous_reading_date": "2026-12-01",
        }
        self.dal.local.cache_consumers([self.consumer])

    def reopen(self):
        store = SQLiteLocalSyncStore(SyncConfig())
        store._db_path = self.path
        return HandheldSyncDataAccess(store, self.remote)

    def bridge(self):
        bridge = SimpleNamespace(
            _consumer=dict(self.consumer), _present_reading="7", _selected_exception="None",
            _reader_name="Test Reader", selectedBillingDate="2026-12-31", _selected_zone="Zone 1",
            _reload_current_consumer_from_db=lambda: None,
            _ensure_current_consumer_receipt_context=lambda **kwargs: None,
            _selected_route=lambda: {},
            _schedule_for_consumer=lambda consumer: {
                "scheduleId": 401, "startDate": "2026-12-31", "dueDate": "2027-01-02",
                "billingMonth": "January 2027",
            },
            _sync_dal=self.dal, _print_preview_busy=False,
            _set_print_preview_busy=Mock(), _set_operation_busy=Mock(),
            printExecutionFinished=SimpleNamespace(emit=Mock()),
        )
        bridge._default_due_date_for_consumer = lambda consumer, day: "2027-01-15"

        def save(consumer_id, present, consumption, exception, flagged, reading_date, due_date, **kwargs):
            return self.dal.queueMeterReading({
                "consumer_id": consumer_id, "present_reading": present, "consumption": consumption,
                "reading_id": kwargs["sync_reading_id"], "reading_date": reading_date,
                "bill_sync_id": kwargs["bill_sync_id"], "bill_date": kwargs["bill_date"],
                "billing_reference": kwargs["billing_reference"], "schedule_id": kwargs["schedule_id"],
            })

        bridge._save_to_sync_layer = save
        return bridge

    def prepare(self, **kwargs):
        with patch("src.handheld_sync._manila_current_date", return_value=date(2026, 12, 30)):
            return self.dal.preReserveAssignedBills([self.consumer, self.consumer], **kwargs)

    def build_job(self, bridge, day=date(2027, 1, 1)):
        with patch("src.qt_hybrid_app.manila_current_date", return_value=day):
            return AppBridge._build_pending_receipt_job(bridge)

    def execute(self, bridge, job):
        bridge._pending_print_job = job
        with patch("src.qt_hybrid_app.threading.Thread", InlineThread), patch(
            "src.qt_hybrid_app.save_reading", return_value=91
        ) as save, patch("src.qt_hybrid_app.save_receipt_print", return_value=92) as history, patch(
            "src.qt_hybrid_app.can_use_system_printer", return_value=True
        ), patch("src.qt_hybrid_app.send_to_system_printer") as printer:
            AppBridge.proceedPrintPreview(bridge)
        result = bridge.printExecutionFinished.emit.call_args.args[0]
        self.assertTrue(result["success"], result)
        save.assert_called_once()
        return result, history, printer

    def assert_offline_reprint_reference(self, reference):
        self.remote.online = False
        bridge = SimpleNamespace(
            _selected_route_consumer_rows=lambda: [{
                **self.consumer, "is_read": True, "reading_value": 7, "consumption": 2,
                "reading_date": "2027-01-01",
            }],
            _sync_dal=self.dal, _reader_name="Test Reader", _selected_zone="Zone 1",
            alertRequested=SimpleNamespace(emit=Mock()),
            canReprintChanged=SimpleNamespace(emit=Mock()),
            receiptPreviewRequested=SimpleNamespace(emit=Mock()),
        )
        with patch("src.qt_hybrid_app.get_latest_receipt_print", return_value=None), patch(
            "src.qt_hybrid_app.save_receipt_print", return_value=93
        ), patch("src.qt_hybrid_app.can_use_system_printer", return_value=True), patch(
            "src.qt_hybrid_app.send_to_system_printer"
        ) as printer:
            AppBridge.reprintZoneConsumer(bridge, 8)
        bridge.alertRequested.emit.assert_not_called()
        printer.assert_called_once()
        self.assertEqual(_receipt_billing_reference(printer.call_args.args[0]), reference)

    def test_future_dates_survive_restart_print_offline_and_upload_exact_reference(self):
        prepared = self.prepare()
        self.assertEqual((prepared["ready"], prepared["reserved"], prepared["failed"]), (3, 3, 0))
        self.assertEqual([day for _, day in self.remote.calls], ["2026-12-31", "2027-01-01", "2027-01-02"])
        self.assertEqual(self.prepare()["reserved"], 0)
        self.assertEqual(len(self.remote.calls), 3)
        self.remote.online = False
        self.dal = self.reopen()
        bridge = self.bridge()
        job = self.build_job(bridge)
        reference = job["billing_reference"]
        self.assertTrue(reference.startswith("SLR2027"))
        self.assertEqual(_receipt_billing_reference(job["receipt_text"]), reference)
        result, history, printer = self.execute(bridge, job)
        self.assertEqual(_receipt_billing_reference(result["receipt_text"]), reference)
        history.assert_called_once()
        printer.assert_called_once_with(result["receipt_text"])
        self.dal = self.reopen()
        pending = self.dal.listPendingSyncReadings()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["payload"]["billing_reference"], reference)
        self.assert_offline_reprint_reference(reference)
        self.remote.online = True
        self.assertEqual(self.dal.syncPendingReadings()["synced"], 1)
        self.assertEqual(self.remote.saved[0]["billing_reference"], reference)
        self.assertEqual(self.remote.saved[0]["bill_sync_id"], job["bill_sync_id"])
        self.dal = self.reopen()
        self.assert_offline_reprint_reference(reference)

    def test_missing_reference_saves_reading_without_printing_or_receipt_history(self):
        self.remote.online = False
        bridge = self.bridge()
        job = self.build_job(bridge)
        self.assertFalse(job["billing_reference"])
        self.assertNotIn("Billing Ref", job["receipt_text"])
        self.assertIn("Sync Now", job["receipt_text"])
        result, history, printer = self.execute(bridge, job)
        self.assertTrue(result["pending_reference"])
        history.assert_not_called()
        printer.assert_not_called()
        self.dal = self.reopen()
        self.assertEqual(len(self.dal.listPendingSyncReadings()), 1)
        self.remote.online = True
        self.assertEqual(self.dal.syncPendingReadings()["synced"], 1)
        self.assertTrue(self.remote.saved[0]["billing_reference"].startswith("SLR2027"))

    def test_expired_online_session_still_allows_local_save_without_printing(self):
        self.remote.reserve_billing_reference = Mock(side_effect=PermissionError("Session expired"))
        bridge = self.bridge()
        job = self.build_job(bridge)
        result, history, printer = self.execute(bridge, job)
        self.assertTrue(result["pending_reference"])
        history.assert_not_called()
        printer.assert_not_called()
        self.assertEqual(len(self.dal.listPendingSyncReadings()), 1)
        sync = self.dal.syncPendingReadings()
        self.assertEqual((sync["synced"], sync["failed"]), (0, 1))
        self.assertEqual(len(self.dal.listPendingSyncReadings()), 1)

    def test_receipt_refresh_cannot_replace_an_original_reference(self):
        original = "Billing Ref    : SLR2027000001\nTOTAL DUE      : PHP   100.00"
        context = {
            "billing_reference": "SLR2027000001",
            "bill": {"billing_reference": "SLR2027000002", "amount_due": 100,
                     "due_date": "2027-01-15", "water_charge": 100},
        }
        bridge = SimpleNamespace(
            _sync_dal=SimpleNamespace(getCachedConsumerContext=lambda consumer_id: context),
            _reader_name="Test Reader",
        )
        refreshed = AppBridge._refresh_saved_receipt_penalty(bridge, {
            "consumer_id": 8, "receipt_text": original, "previous_reading": 5, "present_reading": 7,
        })
        self.assertEqual(refreshed, original)

    def test_preparation_is_bounded_and_retries_lost_response_with_same_bill_id(self):
        self.remote.lose_response = True
        first = self.prepare(through_date="2027-01-01")
        self.assertEqual((first["failed"], first["ready"]), (1, 1))
        lost_bill_id = self.remote.calls[0][0]
        self.dal = self.reopen()
        repeated = self.prepare(through_date="2027-01-01")
        self.assertEqual((repeated["reserved"], repeated["ready"], repeated["failed"]), (1, 2, 0))
        self.assertEqual(self.remote.calls[-1][0], lost_bill_id)
        self.assertEqual(len(self.remote.reservations), 2)

    def test_invalid_backend_reference_is_not_cached_as_reserved(self):
        self.remote.reserve_billing_reference = Mock(return_value={"billing_reference": "N/A"})
        result = self.prepare(through_date="2026-12-31")
        self.assertEqual(result["failed"], 1)
        draft = self.dal.local.get_or_create_bill_reservation(8, "2026-12-31", schedule_id=401)
        self.assertIsNone(draft["billing_reference"])

    def test_old_receipt_without_reference_cannot_be_reprinted(self):
        for action in (AppBridge.reprintLastReceipt, AppBridge.reprintSelectedHistory):
            with self.subTest(action=action.__name__):
                entry = {"receipt_text": "Billing Ref    : N/A"}
                bridge = SimpleNamespace(
                    _last_receipt_entry=entry, _print_history_detail=entry, _paper_status="OK",
                    _refresh_saved_receipt_penalty=lambda entry: entry["receipt_text"],
                    alertRequested=SimpleNamespace(emit=Mock()), _open_print_preview=Mock(),
                )
                action(bridge)
                bridge._open_print_preview.assert_not_called()
                self.assertEqual(bridge.alertRequested.emit.call_args.args[0], "Billing Reference Unavailable")

    def test_history_and_last_receipt_reprints_keep_the_original_reference(self):
        for action in (AppBridge.reprintLastReceipt, AppBridge.reprintSelectedHistory):
            with self.subTest(action=action.__name__):
                entry = {"receipt_text": "Billing Ref    : SLR2027000002"}
                bridge = SimpleNamespace(
                    _last_receipt_entry=entry, _print_history_detail=entry, _paper_status="OK",
                    _refresh_saved_receipt_penalty=lambda entry: entry["receipt_text"],
                    alertRequested=SimpleNamespace(emit=Mock()), _open_print_preview=Mock(),
                )
                action(bridge)
                preview = bridge._open_print_preview.call_args.args[1]
                self.assertEqual(_receipt_billing_reference(preview), "SLR2027000002")
                bridge.alertRequested.emit.assert_not_called()

    def test_sync_never_confirms_a_different_reference_for_immediate_or_queued_uploads(self):
        self.remote.wrong_response_reference = True
        for mode, consumer_id in (("immediate", 80), ("queued", 81)):
            with self.subTest(mode=mode):
                reservation = self.dal.prepareBillingReference(consumer_id, "2027-01-01", schedule_id=401)
                payload = {
                    "consumer_id": consumer_id, "reading_id": reservation["reading_sync_id"],
                    "reading_date": "2027-01-01", "present_reading": 7, "consumption": 2,
                    "schedule_id": 401, "bill_date": reservation["bill_date"],
                    "bill_sync_id": reservation["bill_sync_id"],
                    "billing_reference": reservation["billing_reference"],
                }
                if mode == "immediate":
                    self.assertEqual(self.dal.saveMeterReading(payload)["status"], "conflict")
                else:
                    self.dal.queueMeterReading(payload)
                    self.assertEqual(self.dal.syncPendingReadings()["conflicts"], 1)
                self.assertEqual(self.remote.saved[-1]["billing_reference"], reservation["billing_reference"])
                self.assertEqual(self.dal.local.get_latest_confirmed_bill(consumer_id), {})
                cached = self.dal.local.get_or_create_bill_reservation(consumer_id, "2027-01-01", schedule_id=401)
                self.assertEqual(cached["billing_reference"], reservation["billing_reference"])

    def test_shared_printer_refuses_receipts_without_one_exact_reference(self):
        for receipt in ("Billing Ref: N/A", "Billing Ref:", "Receipt with no reference",
                        "Billing Ref: SLR2027000001\nBilling Ref: SLR2027000002"):
            with self.subTest(receipt=receipt), patch("src.receipt.subprocess.run") as printer:
                with self.assertRaisesRegex(RuntimeError, "exact billing reference"):
                    send_to_system_printer(receipt)
                printer.assert_not_called()


if __name__ == "__main__":
    unittest.main()

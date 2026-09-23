import unittest
import threading
from datetime import date
from types import SimpleNamespace

from src.handheld_sync import _build_bill_payload
from src.receipt import apply_authoritative_bill, build_receipt_text, build_reprint_receipt_text


class ReceiptCoverageTests(unittest.TestCase):
    def setUp(self):
        self.consumer = {
            "id": 42, "classification_id": 1, "classification_name": "Residential",
            "minimum_cubic": 10, "minimum_rate": 100, "excess_rate_per_cubic": 15,
            "due_days": 15, "previous_reading": 5,
            "latest_reading_date": "2026-08-20",
            "date_covered_from": "2026-08-27", "date_covered_to": "2026-08-27",
        }
        self.reading = {
            "consumer_id": 42, "reading_id": "reading-42", "previous_reading": 5,
            "present_reading": 7, "consumption": 2,
            "reading_date": "2026-09-17", "bill_date": "2026-08-27",
            "schedule_date": "2026-08-27", "schedule_due_date": "2026-09-01",
        }

    def test_late_reading_uses_meter_reading_dates_in_bill_receipt_and_reprint(self):
        bill = _build_bill_payload(self.reading, self.consumer, 99, as_of_date=date(2026, 9, 17))
        self.assertEqual(bill["date_covered_from"], "2026-08-20 00:00:00")
        self.assertEqual(bill["date_covered_to"], "2026-09-17 00:00:00")
        receipt = build_receipt_text(
            apply_authoritative_bill(self.consumer, bill), 5, 7, "None", "Juan Dela Cruz",
            reading_date="2026-09-17",
        )
        expected = "Coverage       : 2026-08-20 to\n                  2026-09-17"
        self.assertIn(expected, receipt)
        self.assertIn("Date           : 2026-09-17", receipt)
        self.assertIn(expected, build_reprint_receipt_text(receipt))

    def test_reading_dates_override_schedule_and_backend_bill_dates(self):
        snapshot = dict(self.consumer, schedule_date="2026-08-27", schedule_due_date="2026-09-01")
        snapshot = apply_authoritative_bill(snapshot, {
            "date_covered_from": "2026-09-17", "date_covered_to": "2026-09-17",
        })
        receipt = build_receipt_text(snapshot, 5, 7, "None", "Juan Dela Cruz", reading_date="2026-09-17")
        self.assertIn("Coverage       : 2026-08-20 to\n                  2026-09-17", receipt)

    def test_offline_retry_preserves_previous_reading_snapshot(self):
        reading = dict(self.reading, previous_reading_date="2026-08-20")
        context = dict(self.consumer, latest_reading_date="2026-09-17")
        bill = _build_bill_payload(reading, context, 99)
        self.assertEqual(bill["date_covered_from"], "2026-08-20 00:00:00")
        self.assertEqual(bill["date_covered_to"], "2026-09-17 00:00:00")

    def test_missing_previous_date_does_not_invent_a_schedule_or_month_start(self):
        consumer = dict(self.consumer, previous_reading_date=None)
        bill = _build_bill_payload(dict(self.reading, previous_reading_date=None), consumer, 99)
        self.assertIsNone(bill["date_covered_from"])
        receipt = build_receipt_text(consumer, 0, 7, "None", "Juan Dela Cruz", reading_date="2026-09-17")
        self.assertIn("Coverage       : N/A to\n                  2026-09-17", receipt)

    def test_preview_uses_consumers_linked_schedule_instead_of_current_route(self):
        try:
            from src.qt_hybrid_app import AppBridge
        except ImportError:
            self.skipTest("Qt is not installed")
        reservations = []

        def reserve(consumer_id, bill_date, **kwargs):
            reservations.append((consumer_id, bill_date, kwargs))
            return {"bill_date": bill_date, "billing_reference": "SLR2026000125"}

        bridge = SimpleNamespace(
            _consumer=self.consumer, _present_reading="7", _selected_exception="None",
            _reader_name="Juan Dela Cruz", _due_date="2026-09-01",
            selectedBillingDate="2026-09-17",
            _reload_current_consumer_from_db=lambda: None,
            _ensure_current_consumer_receipt_context=lambda **kwargs: None,
            _selected_route=lambda: {"startDate": "2026-09-17", "dueDate": "2026-09-22"},
            _schedule_for_consumer=lambda consumer: {
                "scheduleId": "538", "startDate": "2026-08-27", "dueDate": "2026-09-01",
                "billingMonth": "August 2026",
            },
            _sync_dal=SimpleNamespace(prepareBillingReference=reserve),
        )
        job = AppBridge._build_pending_receipt_job(bridge)
        self.assertEqual(job["schedule_id"], 538)
        self.assertEqual(job["schedule_date"], "2026-08-27")
        self.assertEqual(job["schedule_due_date"], "2026-09-01")
        self.assertEqual(reservations[0][1], "2026-08-27")
        self.assertEqual(job["previous_reading_date"], "2026-08-20")
        self.assertEqual(job["consumer_snapshot"]["previous_reading_date"], "2026-08-20")
        self.assertIn(
            "Coverage       : 2026-08-20 to\n                  " + job["reading_date"],
            job["receipt_text"],
        )
        # Saving updates the consumer's latest date; the queue must keep the
        # previous date captured when this receipt was prepared.
        bridge._consumer = dict(self.consumer, latest_reading_date=job["reading_date"])
        bridge._meter_reader_account_id = "12"
        bridge._auto_sync_enabled = False
        bridge._sync_dal.operation_lock = threading.Lock()
        bridge._sync_dal.queueMeterReading = lambda payload: payload
        queued = AppBridge._save_to_sync_layer(
            bridge, 42, 7, 2, "None", False, job["reading_date"], job["due_date"],
            previous_reading_date_snapshot=job["previous_reading_date"],
            wait_for_result=True,
        )
        self.assertEqual(queued["previous_reading_date"], "2026-08-20")
        bill = _build_bill_payload(queued, queued, 99)
        self.assertEqual(bill["date_covered_from"], "2026-08-20 00:00:00")
        self.assertEqual(bill["date_covered_to"], job["reading_date"] + " 00:00:00")

import gc
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from src import database, offline_reference_cleanup
from src.handheld_sync import SQLiteLocalSyncStore, SyncConfig
from src.offline_reference_cleanup import cleanup_offline_references


class OfflineReferenceCleanupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "meter.db"
        db_patch = patch.object(database, "_db_path", return_value=str(self.path))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        self.addCleanup(gc.collect)
        database.init_db()
        database.replace_consumers_from_sync([{
            "id": 1, "meter_no": "MTR-1", "name": "Test Consumer", "zone_name": "Zone 1",
        }])
        self.store = SQLiteLocalSyncStore(SyncConfig())
        self.store._db_path = str(self.path)
        self.store.ensure_schema()
        self.today = date(2026, 11, 7)
        self.sequence = 0

    def reservation(self, bill_date="2026-11-06"):
        self.sequence += 1
        row = self.store.get_or_create_bill_reservation(1, bill_date, schedule_id=100 + self.sequence)
        reference = f"SLR2026{self.sequence:06d}"
        self.store.save_reserved_reference(row["bill_sync_id"], reference)
        return {**row, "billing_reference": reference}

    def records(self):
        with sqlite3.connect(self.path) as connection:
            return connection.execute("SELECT bill_sync_id, billing_reference, status FROM local_billing_reference_reservations ORDER BY bill_sync_id").fetchall()

    def test_preview_is_read_only_and_only_old_unused_rows_are_eligible(self):
        self.reservation()
        self.reservation("2026-11-07")
        self.reservation("2026-11-08")
        used = self.reservation()
        self.store.mark_bill_reservation_used(used["bill_sync_id"], 9)
        before = self.records()
        report = cleanup_offline_references(self.path, today=self.today)
        self.assertEqual(report["eligible_old_unused"], 1)
        self.assertFalse(report["applied"])
        self.assertEqual(report["removed"], 0)
        self.assertEqual(self.records(), before)
        self.assertFalse((self.path.parent / "backups").exists())

    def test_all_queue_states_protect_original_references(self):
        for status in ("pending", "failed", "conflict", "needs_review", "synced"):
            row = self.reservation()
            self.store.enqueue_operation("create", {
                "consumer_id": 1, "reading_id": row["reading_sync_id"], "reading_date": row["bill_date"],
                "bill_sync_id": row["bill_sync_id"],
            }, backend_status=status)
        report = cleanup_offline_references(self.path, apply=True, today=self.today)
        self.assertEqual(report["eligible_old_unused"], 0)
        self.assertEqual(report["kept_by_reason"]["linked_to_saved_work"], 5)
        self.assertEqual(len(self.records()), 5)

    def test_saved_reading_and_receipt_and_cached_bill_references_are_kept(self):
        reading = self.reservation()
        database.save_reading(1, 10, 5, sync_reading_id=reading["reading_sync_id"])
        receipt = self.reservation()
        database.save_receipt_print(1, f"Billing Ref: {receipt['billing_reference']}", 0, 1, 1)
        context = self.reservation()
        self.store.cache_consumer_context(1, {"local_bills": [{"sync_id": context["bill_sync_id"]}]})
        cached = self.reservation()
        self.store.cache_consumers([{"id": 1, "meter_no": "MTR-1", "name": "Test Consumer",
                                     "billing_reference": cached["billing_reference"]}])
        before = self.records()
        report = cleanup_offline_references(self.path, apply=True, today=self.today)
        self.assertEqual(report["removed"], 0)
        self.assertEqual(self.records(), before)

    def test_used_reference_also_protects_another_reservation_sharing_its_number(self):
        used = self.reservation()
        self.store.mark_bill_reservation_used(used["bill_sync_id"], 9)
        other = self.reservation()
        self.store.save_reserved_reference(other["bill_sync_id"], used["billing_reference"])
        report = cleanup_offline_references(self.path, apply=True, today=self.today)
        self.assertEqual(report["removed"], 0)
        self.assertEqual(len(self.records()), 2)

    def test_apply_preserves_used_and_current_rows_and_backup_can_be_restored(self):
        old = self.reservation()
        current = self.reservation("2026-11-07")
        used = self.reservation()
        self.store.mark_bill_reservation_used(used["bill_sync_id"], 9)
        before = self.records()
        report = cleanup_offline_references(self.path, apply=True, today=self.today)
        self.assertEqual(report["removed"], 1)
        self.assertEqual(report["remaining_reservations"], 2)
        self.assertEqual({row[0] for row in self.records()}, {current["bill_sync_id"], used["bill_sync_id"]})
        backup = sqlite3.connect(report["backup"])
        restored = sqlite3.connect(":memory:")
        try:
            backup.backup(restored)
            recovered = restored.execute("SELECT bill_sync_id,billing_reference,status FROM local_billing_reference_reservations ORDER BY bill_sync_id").fetchall()
            self.assertEqual(recovered, before)
            self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            backup.close()
            restored.close()
        with sqlite3.connect(self.path) as connection:
            audit = connection.execute("SELECT status,payload FROM sync_audit_log ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(audit[0], "maintenance")
            self.assertEqual(json.loads(audit[1])["removed"], 1)
        repeated = cleanup_offline_references(self.path, apply=True, today=self.today)
        self.assertEqual(repeated["removed"], 0)
        self.assertIsNone(repeated["backup"])

    def test_missing_tables_and_invalid_json_stop_cleanup_without_removing_rows(self):
        self.reservation()
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT INTO handheld_consumer_context_cache (consumer_id,context_json) VALUES (1,'broken-json')")
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            cleanup_offline_references(self.path, apply=True, today=self.today)
        self.assertEqual(len(self.records()), 1)
        with sqlite3.connect(self.path) as connection:
            connection.execute("DELETE FROM handheld_consumer_context_cache")
            connection.execute("DROP TABLE receipt_prints")
        with self.assertRaisesRegex(ValueError, "required columns"):
            cleanup_offline_references(self.path, apply=True, today=self.today)
        self.assertEqual(len(self.records()), 1)
        self.assertFalse((self.path.parent / "backups").exists())

    def test_record_changed_after_backup_is_deferred(self):
        row = self.reservation()
        original_plan = offline_reference_cleanup._plan
        calls = 0

        def plan_and_change(connection, today):
            nonlocal calls
            calls += 1
            result = original_plan(connection, today)
            if calls == 2:
                with sqlite3.connect(self.path) as writer:
                    writer.execute("UPDATE local_billing_reference_reservations SET billing_reference=? WHERE bill_sync_id=?",
                                   ("SLR2026999999", row["bill_sync_id"]))
            return result

        with patch.object(offline_reference_cleanup, "_plan", side_effect=plan_and_change):
            report = cleanup_offline_references(self.path, apply=True, today=self.today)
        self.assertEqual(report["removed"], 0)
        self.assertEqual(report["deferred_changed_records"], 1)
        self.assertEqual(self.records()[0][1], "SLR2026999999")

    def test_missing_database_is_never_created(self):
        missing = self.path.parent / "missing.db"
        with self.assertRaises(FileNotFoundError):
            cleanup_offline_references(missing, apply=True, today=self.today)
        self.assertFalse(missing.exists())

    def test_absent_optional_context_cache_in_older_versions_is_supported(self):
        old = self.reservation()
        current = self.reservation("2026-11-07")
        queued = self.reservation()
        self.store.enqueue_operation("create", {
            "consumer_id": 1, "reading_date": queued["bill_date"], "bill_sync_id": queued["bill_sync_id"],
        })
        with sqlite3.connect(self.path) as connection:
            connection.execute("DROP TABLE handheld_consumer_context_cache")
        report = cleanup_offline_references(self.path, apply=True, today=self.today)
        self.assertEqual(report["removed"], 1)
        self.assertEqual({row[0] for row in self.records()}, {current["bill_sync_id"], queued["bill_sync_id"]})


if __name__ == "__main__":
    unittest.main()

import gc
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src import database, review_cleanup
from src.handheld_sync import HandheldSyncDataAccess, SQLiteLocalSyncStore, SyncConfig


class ReviewCleanupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(gc.collect)
        self.path = Path(directory.name) / 'meter.db'
        db_patch = patch.object(database, '_db_path', return_value=str(self.path))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database.init_db()
        self.store = SQLiteLocalSyncStore(SyncConfig())
        self.store._db_path = str(self.path)
        self.store.ensure_schema()
        schedule = {'schedule_id': 100, 'meter_reader_id': 2, 'zone_name': 'Zone 1',
                    'start_date': '2026-11-16', 'due_date': '2026-11-20', 'status': 'Scheduled'}
        database.replace_reading_schedules_from_sync([schedule], 2, '2026-11-01', '2026-11-30')
        database.replace_consumers_from_sync([{'id': 7, 'meter_no': 'MTR-7', 'name': 'Test',
            'zone_name': 'Zone 1', 'schedule_id': 100, 'previous_reading': 100, 'is_read': False}])
        draft = self.store.get_or_create_bill_reservation(7, '2026-11-16', schedule_id=100)
        self.store.save_reserved_reference(draft['bill_sync_id'], 'SLR2026000999')
        self.payload = {'consumer_id': 7, 'reading_id': draft['reading_sync_id'],
                        'bill_sync_id': draft['bill_sync_id'], 'schedule_id': 100,
                        'reading_date': '2026-11-16', 'previous_reading': 100,
                        'present_reading': 110, 'consumption': 10, 'billing_reference': 'SLR2026000999'}
        self.reading_id = database.save_reading(7, 110, 10, reading_date='2026-11-16',
            schedule_id=100, sync_reading_id=draft['reading_sync_id'], reading_sync_status='needs_review')
        self.queue = self.store.enqueue_operation('create', self.payload, backend_status='needs_review')
        self.store.cache_consumer_context(7, {'local_bill': {'sync_id': draft['bill_sync_id']},
            'local_bills': [{'sync_id': draft['bill_sync_id']}], 'bill': {'sync_id': 'office-bill'}})

    def test_preview_is_read_only(self):
        before = self.path.read_bytes()
        result = review_cleanup.cleanup_reviews(self.path)
        self.assertEqual(result['needs_review'], 1)
        self.assertEqual(result['removed'], 0)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.path.parent / 'backups').exists())

    def test_clear_retains_other_uploads_receipts_references_and_restorable_backup(self):
        database.save_receipt_print(7, 'SLR2026000999', 100, 110, 10, reading_id=self.reading_id)
        for status in ('pending', 'failed', 'conflict', 'synced', 'archived'):
            self.store.enqueue_operation('create', {**self.payload, 'consumer_id': 8, 'reading_id': status,
                'bill_sync_id': status, 'operation_id': status}, backend_status=status)
        before = self.store.list_needs_review()
        result = review_cleanup.cleanup_reviews(self.path, apply=True)
        self.assertEqual((result['removed'], result['retired_local_readings'], result['needs_review']), (1, 1, 0))
        with self.store._connect() as conn:
            states = {row[0] for row in conn.execute('SELECT backend_status FROM sync_queue_meter_readings')}
            self.assertEqual(states, {'pending', 'failed', 'conflict', 'synced', 'archived'})
            self.assertEqual(conn.execute('SELECT reading_status FROM readings WHERE id=?', (self.reading_id,)).fetchone()[0], 'deleted')
            self.assertEqual(tuple(conn.execute('SELECT status,billing_reference FROM local_billing_reference_reservations').fetchone()), ('Discarded', 'SLR2026000999'))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM receipt_prints').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT previous_reading FROM consumers WHERE id=7').fetchone()[0], 100)
            self.assertEqual(conn.execute('SELECT is_read FROM reading_assignment WHERE schedule_id=100').fetchone()[0], 0)
        context = self.store.load_cached_consumer_context(7)
        self.assertNotIn('local_bill', context)
        self.assertEqual(context['local_bills'], [])
        self.assertEqual(context['bill']['sync_id'], 'office-bill')
        with sqlite3.connect(result['backup']) as backup:
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM sync_queue_meter_readings WHERE backend_status='needs_review'").fetchone()[0], len(before))
            self.assertEqual(backup.execute('PRAGMA quick_check').fetchone()[0], 'ok')
        repeated = review_cleanup.cleanup_reviews(self.path, apply=True)
        self.assertEqual(repeated['removed'], 0)
        self.assertIsNone(repeated['backup'])
        next_draft = self.store.get_or_create_bill_reservation(7, '2026-11-16', schedule_id=100)
        self.assertNotEqual(next_draft['bill_sync_id'], self.payload['bill_sync_id'])
        self.assertIsNone(next_draft['billing_reference'])
        database.init_db()
        self.assertEqual(HandheldSyncDataAccess(self.store, None).listReviewReadings(), [])

    def test_newer_offline_reading_preserves_baseline_and_assignment(self):
        database.save_reading(7, 130, 20, reading_date='2026-11-16', schedule_id=100, sync_reading_id='newer')
        with self.store._connect() as conn:
            conn.execute('UPDATE consumers SET latest_reading=105,latest_reading_date=? WHERE id=7', ('2026-11-16',))
        review_cleanup.cleanup_reviews(self.path, apply=True)
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT previous_reading FROM consumers WHERE id=7').fetchone()[0], 130)
            self.assertEqual(conn.execute('SELECT is_read FROM reading_assignment WHERE schedule_id=100').fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT reading_sync_status FROM readings WHERE sync_reading_id='newer'").fetchone()[0], 'pending')

    def test_confirmed_local_reading_is_preserved(self):
        with self.store._connect() as conn:
            conn.execute("UPDATE readings SET reading_sync_status='synced' WHERE id=?", (self.reading_id,))
        review_cleanup.cleanup_reviews(self.path, apply=True)
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT reading_sync_status FROM readings WHERE id=?', (self.reading_id,)).fetchone()[0], 'synced')
            self.assertEqual(conn.execute('SELECT status FROM local_billing_reference_reservations').fetchone()[0], 'Reserved')

    def test_other_saved_operation_keeps_the_assignment_completed(self):
        self.store.enqueue_operation('create', {**self.payload, 'reading_id': 'other',
            'bill_sync_id': 'other', 'operation_id': 'other'}, backend_status='pending')
        review_cleanup.cleanup_reviews(self.path, apply=True)
        with self.store._connect() as conn:
            row = conn.execute('SELECT is_read,reading_sync_status FROM reading_assignment WHERE schedule_id=100').fetchone()
            self.assertEqual(tuple(row), (1, 'pending'))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM sync_queue_meter_readings').fetchone()[0], 1)

    def test_invalid_payload_or_context_rolls_back(self):
        with self.store._connect() as conn:
            conn.execute("UPDATE handheld_consumer_context_cache SET context_json='not-json'")
        with self.assertRaises(ValueError):
            review_cleanup.cleanup_reviews(self.path, apply=True)
        self.assertEqual(len(self.store.list_needs_review()), 1)
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT reading_sync_status FROM readings WHERE id=?', (self.reading_id,)).fetchone()[0], 'needs_review')
            conn.execute('UPDATE sync_queue_meter_readings SET payload=?', (json.dumps({**self.payload, 'reading_id': 'wrong'}),))
        with self.assertRaisesRegex(ValueError, 'inconsistent identifiers'):
            review_cleanup.cleanup_reviews(self.path, apply=True)

    def test_missing_database_is_not_created(self):
        missing = self.path.parent / 'missing.db'
        with self.assertRaises(FileNotFoundError):
            review_cleanup.cleanup_reviews(missing, apply=True)
        self.assertFalse(missing.exists())

    def test_used_reference_and_another_operation_for_same_reading_are_preserved(self):
        self.store.mark_bill_reservation_used(self.payload['bill_sync_id'], 80)
        self.store.enqueue_operation('create', {**self.payload, 'operation_id': 'another-operation'},
                                     backend_status='synced')
        result = review_cleanup.cleanup_reviews(self.path, apply=True)
        self.assertEqual((result['removed'], result['retired_local_readings']), (1, 0))
        with self.store._connect() as conn:
            self.assertEqual(tuple(conn.execute('SELECT status,bill_id,billing_reference FROM local_billing_reference_reservations').fetchone()),
                             ('Used', 80, 'SLR2026000999'))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM sync_queue_meter_readings').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT reading_sync_status FROM readings').fetchone()[0], 'needs_review')

    def test_review_changed_after_backup_is_not_cleared(self):
        original_snapshot = review_cleanup._snapshot
        calls = 0

        def snapshot_and_change(conn):
            nonlocal calls
            result = original_snapshot(conn)
            calls += 1
            if calls == 2:
                with sqlite3.connect(self.path) as writer:
                    writer.execute('UPDATE sync_queue_meter_readings SET last_error=? WHERE id=?',
                                   ('Changed by another operation', self.queue['id']))
            return result

        with patch.object(review_cleanup, '_snapshot', side_effect=snapshot_and_change):
            with self.assertRaisesRegex(ValueError, 'changed during backup'):
                review_cleanup.cleanup_reviews(self.path, apply=True)
        self.assertEqual(len(self.store.list_needs_review()), 1)
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT reading_status FROM readings').fetchone()[0], 'valid')


if __name__ == '__main__':
    unittest.main()

import gc
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src import database
from src.handheld_sync import BackendApiClient, HandheldSyncDataAccess, ReadingReviewRequired, SQLiteLocalSyncStore, SyncConfig


REASON = "Review the account's connection date and existing meter history before billing. Newly registered accounts start at zero automatically."


class InitialBaselineRecoveryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(gc.collect)
        self.path = str(Path(directory.name) / 'meter.db')
        db_patch = patch.object(database, '_db_path', return_value=self.path)
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database.init_db()
        self.store = SQLiteLocalSyncStore(SyncConfig())
        self.store._db_path = self.path
        self.remote = Mock()
        self.remote._meter_reader_id = 2
        self.remote.is_online.return_value = True
        self.remote.load_reading_schedules.return_value = []
        self.remote.find_existing_reading.return_value = None
        self.dal = HandheldSyncDataAccess(self.store, self.remote)
        self.store.cache_reading_schedules([{
            'schedule_id': 100, 'meter_reader_id': 2, 'zone_name': 'Zone 1',
            'start_date': '2026-11-18', 'due_date': '2026-11-18', 'status': 'Scheduled',
        }], 2, '2026-11-01', '2026-11-30')
        database.replace_consumers_from_sync([{'id': 7, 'name': 'Test consumer', 'meter_no': 'MTR-7',
            'zone_name': 'Zone 1', 'schedule_id': 100, 'previous_reading': 0}])
        draft = self.store.get_or_create_bill_reservation(7, '2026-11-18', schedule_id=100)
        self.store.save_reserved_reference(draft['bill_sync_id'], 'SLR2026000999')
        self.payload = {'consumer_id': 7, 'meter_reader_id': 2, 'meter_no': 'MTR-7',
            'reading_id': draft['reading_sync_id'], 'bill_sync_id': draft['bill_sync_id'],
            'billing_reference': 'SLR2026000999', 'schedule_id': 100, 'billing_cycle': '2026-11',
            'reading_date': '2026-11-18', 'bill_date': '2026-11-18', 'schedule_date': '2026-11-18',
            'previous_reading': None, 'present_reading': 23, 'consumption': 23}
        database.save_reading(7, 23, 23, reading_date='2026-11-18', schedule_id=100,
            sync_reading_id=draft['reading_sync_id'], reading_status='rejected', reading_sync_status='conflict')
        self.queue = self.store.enqueue_operation('create', self.payload, backend_status='conflict')
        self.store.mark_conflict(self.queue['id'], REASON, target='backend')
        self.coverage = {'id': 7, 'meter_no': 'MTR-7', 'coverage_policy_version': 1,
            'coverage_from': '2021-01-15', 'previous_reading': 0,
            'coverage_source': 'opening_reading', 'baseline_required': False}
        self.remote.get_consumer_context.return_value = dict(self.coverage)
        self.remote.save_reading_bundle.return_value = {
            'meterreading': {'reading_status': 'Recorded', 'sync_status': 'synced'},
            'bill': {'bill_id': 80, 'sync_id': draft['bill_sync_id'], 'billing_reference': 'SLR2026000999'},
        }

    def test_office_confirmed_zero_recovers_original_reading_and_reference_once(self):
        result = self.dal.syncPendingReadings()
        self.assertEqual((result['synced'], result['needs_review'], result['conflicts']), (1, 0, 0))
        uploaded = self.remote.save_reading_bundle.call_args.args[0]
        for key in ('reading_id', 'bill_sync_id', 'billing_reference', 'reading_date', 'present_reading'):
            self.assertEqual(uploaded[key], self.payload[key])
        self.assertEqual((uploaded['previous_reading'], uploaded['consumption']), (0, 23))
        self.assertEqual(uploaded['coverage_from'], '2021-01-15')
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM readings').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT reading_sync_status FROM readings').fetchone()[0], 'synced')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM local_billing_reference_reservations').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT status FROM local_billing_reference_reservations').fetchone()[0], 'Used')
        self.dal.syncPendingReadings()
        self.assertEqual(self.remote.save_reading_bundle.call_count, 1)

    def test_missing_or_nonzero_or_unverified_baseline_never_guesses_zero(self):
        for change in ({'previous_reading': None, 'baseline_required': True}, {'previous_reading': 10},
                       {'baseline_required': True}, {'coverage_source': 'historical_reading'},
                       {'coverage_from': '2026-11-19'}, {'coverage_policy_version': None}):
            with self.subTest(change=change):
                self.remote.get_consumer_context.return_value = {**self.coverage, **change}
                result = self.dal.syncPendingReadings()
                self.assertEqual((result['synced'], result['needs_review']), (0, 1))
                self.remote.save_reading_bundle.assert_not_called()
                self.assertIsNone(self.store.list_needs_review()[0]['payload']['previous_reading'])

    def test_other_account_meter_reader_or_existing_reading_is_not_recovered(self):
        for change in ({'id': 8}, {'meter_no': 'OTHER-METER'}):
            self.remote.get_consumer_context.return_value = {**self.coverage, **change}
            self.dal.syncPendingReadings()
            self.remote.save_reading_bundle.assert_not_called()
        self.remote.get_consumer_context.return_value = self.coverage
        self.remote._meter_reader_id = 3
        self.dal.syncPendingReadings()
        self.remote.save_reading_bundle.assert_not_called()
        self.remote._meter_reader_id = 2
        self.remote.find_existing_reading.return_value = {'reading_id': 90, 'consumer_id': 7}
        self.dal.syncPendingReadings()
        self.remote.save_reading_bundle.assert_not_called()

    def test_offline_or_unavailable_office_keeps_original_saved_entry(self):
        self.remote.is_online.return_value = False
        self.dal.syncPendingReadings()
        self.remote.get_consumer_context.assert_not_called()
        self.remote.is_online.return_value = True
        self.remote.get_consumer_context.side_effect = ConnectionError('Office unavailable')
        self.dal.syncPendingReadings()
        self.assertIsNone(self.store.list_needs_review()[0]['payload']['previous_reading'])
        self.remote.save_reading_bundle.assert_not_called()

    def office_bill(self):
        saved = {'reading_id': 90, 'consumer_id': 7, 'schedule_id': 100,
            'reading_date': '2026-11-18', 'updated_at': '2026-11-18T12:30:00',
            'previous_reading': '0.00', 'present_reading': '23.00', 'consumption': '23.00',
            'reading_status': 'Recorded', 'sync_status': 'synced', 'sync_id': 'office-reading',
            'billing_cycle': '2026-11', 'bill': {'bill_id': 93, 'sync_id': 'office-bill',
                'billing_reference': 'SLR2026001056', 'bill_month': '2026-11', 'status': 'Unpaid'}}
        self.remote.find_existing_reading.return_value = saved
        self.remote.get_consumer_context.return_value = {**self.coverage, 'previous_reading': 23,
            'coverage_source': 'historical_reading', 'latest_reading': 23, 'latest_reading_date': '2026-11-18'}
        return saved

    def test_office_created_first_bill_archives_old_baseline_hold_and_retains_original_evidence(self):
        saved = self.office_bill()
        with self.store._connect() as conn:
            original = conn.execute('SELECT payload FROM sync_queue_meter_readings WHERE id=?', (self.queue['id'],)).fetchone()[0]
        result = self.dal.syncPendingReadings()
        self.assertEqual((result['ignored_duplicates'], result['needs_review'], result['synced']), (1, 0, 0))
        self.remote.save_reading_bundle.assert_not_called()
        archived = self.store.list_archived_reviews()[0]
        self.assertIsNone(archived['payload']['previous_reading'])
        self.assertEqual(archived['payload']['billing_reference'], 'SLR2026000999')
        self.assertEqual(archived['review_server_record']['reference'], saved['bill']['billing_reference'])
        self.assertEqual(archived['review_server_record']['reading_id'], 90)
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT payload FROM sync_queue_meter_readings WHERE id=?', (self.queue['id'],)).fetchone()[0], original)
            self.assertEqual(conn.execute('SELECT previous_reading FROM consumers WHERE id=7').fetchone()[0], 23)
            reservation = conn.execute('SELECT status,billing_reference FROM local_billing_reference_reservations').fetchone()
            self.assertEqual((reservation['status'], reservation['billing_reference']), ('Reserved', 'SLR2026000999'))
        self.assertEqual(self.dal.syncPendingReadings()['needs_review'], 0)
        self.assertEqual(len(self.store.list_archived_reviews()), 1)

    def test_office_first_bill_requires_same_consumer_cycle_values_and_active_bill(self):
        for change in ({'consumer_id': 8}, {'billing_cycle': '2026-10'}, {'previous_reading': 2},
                       {'present_reading': 24}, {'consumption': 24}, {'bill': None},
                       {'bill': {'bill_id': 93, 'bill_month': '2026-10', 'status': 'Unpaid'}},
                       {'bill': {'bill_id': 93, 'bill_month': '2026-11', 'status': 'Cancelled'}},
                       {'reading_status': 'Rejected'}):
            with self.subTest(change=change):
                saved = self.office_bill()
                saved.update(change)
                result = self.dal.syncPendingReadings()
                self.assertEqual((result['ignored_duplicates'], result['needs_review']), (0, 1))
                self.assertEqual(self.store.list_archived_reviews(), [])
                self.remote.save_reading_bundle.assert_not_called()

    def test_office_first_bill_requires_original_reader_and_meter_and_fresh_verification(self):
        self.office_bill()
        self.remote._meter_reader_id = 3
        self.assertEqual(self.dal.syncPendingReadings()['needs_review'], 1)
        self.remote._meter_reader_id = 2
        self.remote.get_consumer_context.return_value['meter_no'] = 'OTHER-METER'
        self.assertEqual(self.dal.syncPendingReadings()['needs_review'], 1)
        self.office_bill()
        self.remote.find_existing_reading.side_effect = [self.remote.find_existing_reading.return_value, None]
        self.assertEqual(self.dal.syncPendingReadings()['needs_review'], 1)
        self.assertEqual(self.store.list_archived_reviews(), [])

    def test_restored_history_stays_in_review_instead_of_being_archived_again(self):
        self.office_bill()
        self.dal.syncPendingReadings()
        self.dal.restoreReviewEntry(self.queue['id'])
        self.assertEqual(self.dal.syncPendingReadings()['needs_review'], 1)
        self.remote.save_reading_bundle.assert_not_called()

    def test_changed_saved_payload_requires_another_verification(self):
        row = self.store.list_initial_baseline_holds()[0]
        with self.store._connect() as conn:
            conn.execute('UPDATE sync_queue_meter_readings SET payload=? WHERE id=?',
                         (json.dumps({**self.payload, 'present_reading': 24}), row['id']))
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.store.resume_initial_reading(row['id'], row['payload'], self.coverage)
        self.assertEqual(self.store.list_initial_baseline_holds()[0]['payload']['present_reading'], 24)

    def test_existing_nonzero_payload_and_unrelated_conflicts_are_never_reset(self):
        self.remote.get_consumer_context.return_value = {'id': 7, 'previous_reading': 0}
        with self.store._connect() as conn:
            conn.execute('UPDATE sync_queue_meter_readings SET payload=? WHERE id=?',
                         (json.dumps({**self.payload, 'previous_reading': 5, 'consumption': 18}), self.queue['id']))
        self.dal.syncPendingReadings()
        self.remote.get_consumer_context.assert_not_called()
        with self.store._connect() as conn:
            row = conn.execute('SELECT payload FROM sync_queue_meter_readings WHERE id=?', (self.queue['id'],)).fetchone()
            self.assertEqual(json.loads(row['payload'])['previous_reading'], 5)

    def test_baseline_setup_error_is_review_instead_of_duplicate_or_reserved_reference_conflict(self):
        client = BackendApiClient(SyncConfig())
        client._req = Mock(return_value=(409, {'message': REASON}))
        with self.assertRaisesRegex(ReadingReviewRequired, 'connection date'):
            client.save_reading_bundle(self.payload)


if __name__ == '__main__':
    unittest.main()

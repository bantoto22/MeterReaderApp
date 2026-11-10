import gc
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from src import database
from src.handheld_sync import HandheldSyncDataAccess, SQLiteLocalSyncStore, SyncConfig, ReadingReviewRequired
from src.qt_hybrid_app import _group_route_rows


class ActiveScheduleSyncTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(gc.collect)
        self.path = str(Path(directory.name) / 'isolated.db')
        self.db_patch = patch.object(database, '_db_path', return_value=self.path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        database.init_db()
        self.store = SQLiteLocalSyncStore(SyncConfig())
        self.store._db_path = self.path
        self.remote = Mock()
        self.remote.is_online.return_value = True
        self.remote.load_reading_schedules.return_value = []
        self.remote.find_existing_reading.return_value = None
        self.dal = HandheldSyncDataAccess(self.store, self.remote)
        self.payload = {'consumer_id': 7, 'meter_reader_id': 2, 'schedule_id': 100,
            'reading_id': 'saved-reading', 'bill_sync_id': 'saved-bill',
            'reading_date': '2026-11-10', 'bill_date': '2026-11-10',
            'billing_reference': 'SLR2026000999', 'present_reading': 30, 'consumption': 10}

    def test_expired_schedules_never_appear_in_current_or_future_work(self):
        today = date(2026, 11, 10)
        rows = [{'schedule_id': 1, 'start_date': '2026-11-01', 'due_date': '2026-11-09', 'unread_count': 5},
                {'schedule_id': 2, 'start_date': '2026-11-10', 'due_date': '2026-11-12', 'unread_count': 1}]
        groups = _group_route_rows(rows, today)
        self.assertEqual(len(groups), 1)
        self.assertEqual([row['scheduleId'] for row in groups[0]['viewSchedules']], ['2'])
        self.assertEqual(groups[0]['carryOverUnreadCount'], 0)

    def test_api_billing_cycle_is_preserved_in_both_schedule_caches(self):
        today = date.today().isoformat()
        cycle = today[:7]
        schedule = {'Schedule_ID': 100, 'Start_Date': today, 'Due_Date': today,
                    'Zone_Name': 'Zone 1', 'Meter_Reader_ID': 2, 'Billing_Cycle': cycle}
        self.store.cache_reading_schedules([schedule], 2, today, today)
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT billing_month FROM reading_schedule').fetchone()[0], cycle)
        database.replace_reading_schedules_from_sync([schedule], 2, today, today)
        self.assertEqual(_group_route_rows(database.get_assigned_routes(2))[0]['billingMonth'], cycle)

    def test_duplicate_is_retained_once_for_review_without_blocking_normal_readings(self):
        self.dal.queueMeterReading(dict(self.payload))
        normal = {**self.payload, 'consumer_id': 8, 'reading_id': 'normal-reading', 'bill_sync_id': 'normal-bill'}
        self.dal.queueMeterReading(normal)
        def upload(payload):
            if payload['consumer_id'] == 7:
                raise ReadingReviewRequired('This concessionaire already has a bill for 2026-11.')
            return {'meterreading': {'reading_status': 'Recorded', 'sync_status': 'synced'},
                    'bill': {'bill_id': 22, 'sync_id': payload['bill_sync_id'], 'billing_reference': payload['billing_reference']}}
        self.remote.save_reading_bundle.side_effect = upload
        with patch.object(self.dal, '_ensure_billing_reference', side_effect=lambda payload: payload):
            result = self.dal.syncPendingReadings()
        self.assertEqual((result['synced'],result['failed'],result['conflicts'],result['needs_review']), (1,0,0,1))
        self.assertEqual(result['errors'], [])
        self.assertEqual(self.dal.listReviewReadings()[0]['payload']['billing_reference'], self.payload['billing_reference'])
        self.assertEqual(self.dal.syncPendingReadings()['needs_review'], 1)
        self.assertEqual(self.remote.save_reading_bundle.call_count, 2)
        reopened = SQLiteLocalSyncStore(SyncConfig())
        reopened._db_path = self.path
        self.assertEqual(reopened.list_needs_review()[0]['payload']['reading_id'], self.payload['reading_id'])

    def test_stale_failed_duplicate_moves_to_review_without_deleting_its_payload(self):
        self.dal.queueMeterReading(dict(self.payload))
        queued = self.dal.listPendingSyncReadings()[0]
        self.store.mark_target_failed(queued['id'], 'backend', 'This concessionaire is already read for 2026-11.')
        self.dal.reconcileScheduleReadings()
        self.assertEqual(len(self.dal.listPendingSyncReadings()), 0)
        self.assertEqual(self.dal.listReviewReadings()[0]['payload'], queued['payload'])

    def test_capture_after_deadline_is_held_but_valid_offline_captures_can_sync_later(self):
        invalid = {**self.payload,'schedule_date':'2026-11-01','schedule_due_date':'2026-11-09'}
        self.dal.queueMeterReading(invalid)
        self.dal.reconcileScheduleReadings()
        self.assertEqual(len(self.dal.listReviewReadings()),1)
        self.assertEqual(self.remote.save_reading_bundle.call_count,0)
        self.store.mark_needs_review(1,'review')
        valid = {**self.payload,'consumer_id':8,'reading_id':'offline-reading','bill_sync_id':'offline-bill',
                 'schedule_date':'2026-11-01','schedule_due_date':'2026-11-10'}
        self.dal.queueMeterReading(valid)
        self.assertEqual(len(self.dal.listPendingSyncReadings()),1)

    def test_old_duplicate_conflict_is_reclassified_even_after_an_earlier_network_failure(self):
        self.dal.queueMeterReading(dict(self.payload))
        queued = self.dal.listPendingSyncReadings()[0]
        self.store.mark_target_failed(queued['id'],'backend','Connection timeout')
        self.store.mark_conflict(queued['id'],'This concessionaire already has a bill for 2026-11.',target='backend')
        self.dal.reconcileScheduleReadings()
        self.assertEqual(len(self.dal.listReviewReadings()),1)
        self.assertEqual(self.dal.listReviewReadings()[0]['payload'],queued['payload'])

    def test_legacy_failed_capture_uses_cached_deadline_without_changing_payload(self):
        self.store.cache_reading_schedules([{'Schedule_ID':100,'Start_Date':'2026-10-09',
            'Due_Date':'2026-10-13','Zone_Name':'Zone 1','Meter_Reader_ID':2,
            'Billing_Cycle':'2026-10','Status':'Scheduled'}],2,'2026-10-01','2026-10-31')
        self.dal.queueMeterReading(dict(self.payload))
        queued = self.dal.listReviewReadings()[0]
        self.assertEqual(queued['payload']['billing_reference'],self.payload['billing_reference'])
        self.assertNotIn('schedule_due_date',queued['payload'])
        self.assertIn('outside',queued['last_error'])
        self.assertEqual(self.dal.syncPendingReadings()['failed'],0)
        self.remote.save_reading_bundle.assert_not_called()

    def test_expired_assignments_do_not_reserve_new_billing_references(self):
        expired = {'consumer_id':7,'schedule_id':100,'schedule_date':'2026-10-09',
                   'schedule_due_date':'2026-10-13','billing_cycle':'2026-10'}
        with patch('src.handheld_sync._manila_current_date',return_value=date(2026,11,10)):
            result = self.dal.preReserveAssignedBills([expired],through_date='2026-11-30')
        self.assertEqual((result['ready'],result['failed'],result['skipped']),(0,0,1))
        self.remote.reserve_billing_reference.assert_not_called()

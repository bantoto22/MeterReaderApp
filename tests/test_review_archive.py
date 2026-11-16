import gc
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import database
from src.handheld_sync import BackendApiClient,HandheldSyncDataAccess,SQLiteLocalSyncStore,SyncConfig


class ReviewArchiveTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(gc.collect)
        self.path=str(Path(directory.name)/'isolated.db')
        db_path=patch.object(database,'_db_path',return_value=self.path)
        db_path.start();self.addCleanup(db_path.stop)
        database.init_db()
        self.store=SQLiteLocalSyncStore(SyncConfig());self.store._db_path=self.path
        self.remote=Mock();self.remote._meter_reader_id=2;self.remote.is_online.return_value=True
        self.dal=HandheldSyncDataAccess(self.store,self.remote)
        schedule={'Schedule_ID':100,'Start_Date':'2026-11-11','Due_Date':'2026-11-12','Meter_Reader_ID':2,'Zone_Name':'Zone 1','Billing_Cycle':'2026-11'}
        self.store.cache_reading_schedules([schedule],2,'2026-11-01','2026-11-30')
        database.replace_consumers_from_sync([{'id':7,'meter_no':'MTR-7','name':'Test consumer','zone_name':'Zone 1','previous_reading':100,'schedule_id':100,'is_read':False}])
        draft=self.store.get_or_create_bill_reservation(7,'2026-11-11',schedule_id=100)
        self.store.save_reserved_reference(draft['bill_sync_id'],'SLR2026000999')
        self.payload={'consumer_id':7,'meter_reader_id':2,'schedule_id':100,'reading_date':'2026-11-11',
            'billing_cycle':'2026-11','reading_id':draft['reading_sync_id'],'bill_sync_id':draft['bill_sync_id'],
            'previous_reading':100,'present_reading':110,'consumption':10,'billing_reference':'SLR2026000999'}
        database.save_reading(7,110,10,reading_date='2026-11-11',schedule_id=100,sync_reading_id=draft['reading_sync_id'])
        row=self.store.enqueue_operation('create',self.payload,backend_status='pending')
        self.queue_id=row['id']
        self.store.mark_needs_review(self.queue_id,'This concessionaire already has a bill for 2026-11.')
        self.saved={'reading_id':77,'consumer_id':7,'schedule_id':99,'reading_date':'2026-11-11',
            'updated_at':'2026-11-11T09:00:00','previous_reading':'100.00','present_reading':'110.00','consumption':'10.00',
            'reading_status':'Recorded','sync_status':'synced','sync_id':str(uuid.uuid4()),'billing_cycle':'2026-11',
            'bill':{'bill_id':80,'sync_id':str(uuid.uuid4()),'billing_reference':'SLR2026000100','bill_month':'2026-11','status':'Unpaid'}}
        self.remote.find_existing_reading.return_value=self.saved
        self.remote.get_consumer_context.side_effect=lambda *args,**kwargs: {
            'id':7,'meter_no':'MTR-7','name':'Test consumer','zone_name':'Zone 1',
            'previous_reading':float(self.saved['present_reading']),
            'latest_reading':float(self.saved['present_reading']),'latest_reading_date':self.saved['reading_date']}

    def original_json(self):
        with self.store._connect() as conn:
            return conn.execute('SELECT payload FROM sync_queue_meter_readings WHERE id=?',(self.queue_id,)).fetchone()[0]

    def test_verified_duplicate_moves_to_history_without_deletion_or_fake_sync(self):
        original=self.original_json()
        checked=self.dal.checkReviewEntry(self.queue_id)
        self.assertEqual(checked['office']['reference'],'SLR2026000100')
        self.assertFalse(checked['values_differ'])
        self.assertEqual(self.dal.resolveReviewEntry(self.queue_id,checked['token']),'archived')
        self.assertEqual(self.dal.listReviewReadings(),[])
        self.assertEqual(self.dal.listPendingSyncReadings(),[])
        self.assertEqual(self.original_json(),original)
        archived=self.store.list_archived_reviews()[0]
        self.assertEqual((archived['status'],archived['backend_status']),('archived','archived'))
        self.assertIsNone(archived['synced_at'])
        self.assertEqual(archived['review_server_record']['reading_id'],77)
        with self.store._connect() as conn:
            reservation=conn.execute('SELECT * FROM local_billing_reference_reservations').fetchone()
            self.assertEqual((reservation['status'],reservation['billing_reference']),('Reserved','SLR2026000999'))
            reading=conn.execute('SELECT * FROM readings').fetchone()
            self.assertEqual((reading['present_reading'],reading['sync_reading_id']),(110,self.payload['reading_id']))
        self.remote.save_reading_bundle.assert_not_called()
        self.remote.reserve_billing_reference.assert_not_called()
        reopened=SQLiteLocalSyncStore(SyncConfig());reopened._db_path=self.path
        restarted=HandheldSyncDataAccess(reopened,self.remote)
        self.assertEqual(restarted.reviewEntries(True)[0]['office']['reference'],'SLR2026000100')
        restarted.restoreReviewEntry(self.queue_id)
        self.assertEqual(len(restarted.reviewEntries()),1)
        self.assertEqual(restarted.reviewEntries(True),[])
        self.assertEqual(restarted.listPendingSyncReadings(),[])
        self.assertEqual(self.original_json(),original)

    def test_online_office_verification_is_required_and_missing_record_cannot_clear_entry(self):
        self.remote.is_online.return_value=False
        with self.assertRaises(ConnectionError):self.dal.checkReviewEntry(self.queue_id)
        self.remote.is_online.return_value=True
        self.remote.find_existing_reading.return_value=None
        with self.assertRaisesRegex(ValueError,'No matching office reading'):self.dal.checkReviewEntry(self.queue_id)
        self.assertEqual(len(self.dal.listReviewReadings()),1)
        self.assertFalse(self.dal.reviewEntries()[0]['can_resolve'])

    def test_changed_office_record_or_changed_local_payload_requires_another_review(self):
        checked=self.dal.checkReviewEntry(self.queue_id)
        self.saved['present_reading']='111.00'
        with self.assertRaisesRegex(ValueError,'changed'):self.dal.resolveReviewEntry(self.queue_id,checked['token'])
        self.assertEqual(len(self.dal.listReviewReadings()),1)
        checked=self.dal.checkReviewEntry(self.queue_id)
        with self.store._connect() as conn:
            conn.execute('UPDATE sync_queue_meter_readings SET payload=? WHERE id=?',
                (json.dumps({**self.payload,'present_reading':112}),self.queue_id));conn.commit()
        with self.assertRaisesRegex(ValueError,'changed'):self.dal.resolveReviewEntry(self.queue_id,checked['token'])
        self.assertEqual(len(self.dal.listReviewReadings()),1)

    def test_exact_office_ids_values_and_reference_can_confirm_real_sync(self):
        self.saved['sync_id']=self.payload['reading_id']
        self.saved['bill'].update(sync_id=self.payload['bill_sync_id'],billing_reference=self.payload['billing_reference'])
        checked=self.dal.checkReviewEntry(self.queue_id)
        self.assertEqual(checked['action'],'confirm_synced')
        self.assertEqual(self.dal.resolveReviewEntry(self.queue_id,checked['token']),'synced')
        self.assertEqual(self.dal.reviewEntries(True),[])
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT backend_status FROM sync_queue_meter_readings').fetchone()[0],'synced')
            self.assertEqual(conn.execute('SELECT status,bill_id FROM local_billing_reference_reservations').fetchone()['bill_id'],80)

    def test_office_correction_with_same_id_is_archived_without_falsely_acknowledging_original_reference(self):
        self.saved['sync_id']=self.payload['reading_id']
        result=self.dal.syncPendingReadings()
        self.assertEqual((result['ignored_duplicates'],result['needs_review']),(1,0))
        self.assertEqual(self.store.list_archived_reviews()[0]['payload']['billing_reference'],self.payload['billing_reference'])
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT status FROM local_billing_reference_reservations').fetchone()[0],'Reserved')

    def test_nonduplicate_other_account_other_month_and_other_reader_cannot_be_archived(self):
        self.store.mark_needs_review(self.queue_id,'Reading captured outside its assignment dates.')
        with self.assertRaisesRegex(ValueError,'not a confirmed duplicate'):self.dal.checkReviewEntry(self.queue_id)
        self.store.mark_needs_review(self.queue_id,'This concessionaire already has a bill for 2026-11.')
        self.saved['consumer_id']=8
        with self.assertRaisesRegex(ValueError,'another account'):self.dal.checkReviewEntry(self.queue_id)
        self.saved['consumer_id']=7;self.saved['billing_cycle']='2026-10'
        with self.assertRaisesRegex(ValueError,'billing month'):self.dal.checkReviewEntry(self.queue_id)
        self.saved['billing_cycle']='2026-11';self.remote._meter_reader_id=3
        with self.assertRaises(PermissionError):self.dal.checkReviewEntry(self.queue_id)
        self.assertEqual(len(self.dal.listReviewReadings()),1)

    def test_differing_values_are_visible_for_explicit_office_confirmation(self):
        self.saved.update(present_reading='115.00',consumption='15.00')
        checked=self.dal.checkReviewEntry(self.queue_id)
        entry=self.dal.reviewEntries()[0]
        self.assertTrue(entry['values_differ'])
        self.assertEqual((entry['present'],entry['office']['present']),(110,'115'))
        self.dal.resolveReviewEntry(self.queue_id,checked['token'])
        self.assertEqual(self.store.list_archived_reviews()[0]['payload']['present_reading'],110)
        database.init_db()
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT previous_reading FROM consumers WHERE id=7').fetchone()[0],115)

    def test_archive_refreshes_office_baseline_and_excludes_unissued_local_draft_after_restart(self):
        database.save_reading(7,105,5,reading_date='2026-11-01',reading_sync_status='synced')
        self.dal.cacheLocalBill(7,{'sync_id':self.payload['bill_sync_id'],'current_reading':110})
        self.remote.get_consumer_context.side_effect=None
        self.remote.get_consumer_context.return_value={'id':7,'meter_no':'MTR-7','previous_reading':125,
            'latest_reading':125,'latest_reading_date':'2026-11-12'}
        checked=self.dal.checkReviewEntry(self.queue_id)
        self.dal.resolveReviewEntry(self.queue_id,checked['token'])
        self.remote.get_consumer_context.assert_called_once_with(7,include_today=True)
        self.assertNotIn('local_bill',self.dal.getCachedConsumerContext(7))
        self.assertEqual(self.dal.getCachedConsumerContext(7)['local_bills'],[])
        database.init_db()
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT previous_reading FROM consumers WHERE id=7').fetchone()[0],125)
        self.assertEqual(self.original_json(),json.dumps(self.payload))

    def test_archive_preserves_newer_pending_offline_work_and_unavailable_baseline_stays_in_review(self):
        checked=self.dal.checkReviewEntry(self.queue_id)
        self.remote.get_consumer_context.side_effect=ConnectionError('Offline')
        with self.assertRaises(ConnectionError):self.dal.resolveReviewEntry(self.queue_id,checked['token'])
        self.assertEqual(len(self.dal.listReviewReadings()),1)
        self.remote.get_consumer_context.side_effect=None
        self.remote.get_consumer_context.return_value={'id':7,'meter_no':'MTR-7','previous_reading':115,
            'latest_reading':115,'latest_reading_date':'2026-11-11'}
        database.save_reading(7,130,15,reading_date='2026-11-12',sync_reading_id=str(uuid.uuid4()))
        checked=self.dal.checkReviewEntry(self.queue_id)
        self.dal.resolveReviewEntry(self.queue_id,checked['token'])
        database.init_db()
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT previous_reading FROM consumers WHERE id=7').fetchone()[0],130)

    def test_bill_reason_uses_the_office_bill_month_not_an_expired_assignment_cycle(self):
        with self.store._connect() as conn:
            conn.execute('UPDATE sync_queue_meter_readings SET payload=? WHERE id=?',
                (json.dumps({**self.payload,'billing_cycle':'2026-10'}),self.queue_id));conn.commit()
        self.dal.checkReviewEntry(self.queue_id)
        self.remote.find_existing_reading.assert_called_with(7,'2026-11-11',billing_cycle='2026-11',include_bill_month=True)

    def test_reading_only_duplicate_can_be_archived_but_missing_bill_is_not_proof_of_a_bill_duplicate(self):
        self.saved['bill']=None
        with self.assertRaisesRegex(ValueError,'No active office bill'):self.dal.checkReviewEntry(self.queue_id)
        self.store.mark_needs_review(self.queue_id,'This concessionaire is already read for 2026-11.')
        self.assertEqual(self.dal.checkReviewEntry(self.queue_id)['action'],'archive')

    def test_unchecked_entries_and_old_backend_response_are_not_cleared(self):
        with self.assertRaisesRegex(ValueError,'Check the office record'):self.dal.resolveReviewEntry(self.queue_id,'invented-token')
        self.saved.pop('previous_reading')
        with self.assertRaisesRegex(ValueError,'Restart the updated backend'):self.dal.checkReviewEntry(self.queue_id)
        self.assertEqual(len(self.dal.listReviewReadings()),1)

    def test_backend_client_preserves_explicit_review_month_and_optional_bill_lookup(self):
        client=BackendApiClient(SyncConfig(backend_api_base_url='https://isolated.example.test/api'))
        client._req=Mock(return_value=(200,self.saved))
        client.find_existing_reading(7,'2026-11-11',billing_cycle='2026-10',include_bill_month=True)
        self.assertEqual(client._req.call_args.kwargs['query'],{'consumer_id':7,'reading_date':'2026-11-11','billing_cycle':'2026-10','include_bill_month':'1'})
        client.get_consumer_context(7,include_today=True)
        self.assertEqual(client._req.call_args.kwargs['query'],{'include_today':'1'})

    def test_sync_automatically_ignores_existing_review_duplicates_without_uploading_or_manual_confirmation(self):
        original=self.original_json()
        result=self.dal.syncPendingReadings()
        self.assertEqual((result['ignored_duplicates'],result['needs_review'],result['failed'],result['conflicts']),(1,0,0,0))
        self.remote.save_reading_bundle.assert_not_called()
        self.assertEqual(self.original_json(),original)
        self.assertEqual(len(self.dal.reviewEntries(True)),1)
        database.init_db()
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT is_read FROM reading_assignment WHERE consumer_id=7 AND schedule_id=100').fetchone()[0],1)
        self.assertEqual(self.dal.syncPendingReadings()['needs_review'],0)
        self.remote.save_reading_bundle.assert_not_called()

    def test_sync_ignores_newly_detected_duplicates_and_continues_other_pending_work(self):
        with self.store._connect() as conn:
            conn.execute("UPDATE sync_queue_meter_readings SET backend_status='pending',status='pending',last_error=NULL");conn.commit()
        self.remote.load_reading_schedules.return_value=[]
        other={**self.payload,'consumer_id':8,'operation_id':str(uuid.uuid4()),'reading_id':str(uuid.uuid4()),'bill_sync_id':str(uuid.uuid4())}
        self.store.enqueue_operation('create',other,backend_status='pending')
        self.remote.find_existing_reading.side_effect=lambda cid,*args,**kwargs:self.saved if cid==7 else None
        self.remote.save_reading_bundle.return_value={'meterreading':{'reading_status':'Recorded','sync_status':'synced'},
            'bill':{'bill_id':81,'sync_id':other['bill_sync_id'],'billing_reference':other['billing_reference']}}
        result=self.dal.syncPendingReadings()
        self.assertEqual((result['ignored_duplicates'],result['synced'],result['needs_review'],result['failed']),(1,1,0,0))
        self.assertEqual(self.remote.save_reading_bundle.call_count,1)
        self.assertEqual(self.remote.save_reading_bundle.call_args.args[0]['consumer_id'],8)

    def test_office_unavailable_or_unrelated_issue_is_never_silently_removed(self):
        self.remote.find_existing_reading.return_value=None
        result=self.dal.syncPendingReadings()
        self.assertEqual(result['needs_review'],1)
        self.assertEqual(self.dal.reviewEntries(True),[])
        self.store.mark_needs_review(self.queue_id,'Reading captured outside its assigned schedule dates.')
        self.remote.find_existing_reading.return_value=self.saved
        self.assertEqual(self.dal.syncPendingReadings()['needs_review'],1)

    def test_old_duplicate_failure_is_automatically_ignored_after_office_verification(self):
        self.store.mark_target_failed(self.queue_id,'backend','This concessionaire is already read for 2026-11.')
        result=self.dal.syncPendingReadings()
        self.assertEqual((result['ignored_duplicates'],result['failed'],result['needs_review']),(1,0,0))
        self.assertEqual(self.dal.listPendingSyncReadings(),[])

    def test_clearing_one_duplicate_does_not_hide_an_unresolved_saved_reading(self):
        from src.qt_hybrid_app import AppBridge
        other={**self.payload,'consumer_id':8,'operation_id':str(uuid.uuid4()),'reading_id':str(uuid.uuid4()),'bill_sync_id':str(uuid.uuid4()),'billing_reference':'SLR2026000998'}
        row=self.store.enqueue_operation('create',other,backend_status='pending')
        self.store.mark_needs_review(row['id'],'Reading captured outside its assigned schedule dates.')
        checked=self.dal.checkReviewEntry(self.queue_id)
        self.dal.resolveReviewEntry(self.queue_id,checked['token'])
        view=SimpleNamespace(_sync_dal=self.dal,_sync_review_count=99,_sync_review_summary='stale',
            syncReviewCountChanged=SimpleNamespace(emit=Mock()),reviewEntriesChanged=SimpleNamespace(emit=Mock()))
        AppBridge.refreshReviewEntries(view)
        self.assertEqual(view._sync_review_count,1)
        self.assertIn('Consumer 8',view._sync_review_summary)
        self.assertEqual(len(view._archived_review_entries),1)
        self.assertEqual(self.dal.listPendingSyncReadings(),[])


if __name__=='__main__':unittest.main()

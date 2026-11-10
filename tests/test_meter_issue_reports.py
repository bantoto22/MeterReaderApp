import gc
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import database
from src.handheld_sync import BackendApiClient, HandheldSyncDataAccess, SQLiteLocalSyncStore, SyncConfig
from src.qt_hybrid_app import AppBridge


class MeterIssueReportTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(gc.collect)
        self.path=str(Path(directory.name)/'isolated.db')
        database_path=patch.object(database,'_db_path',return_value=self.path)
        database_path.start()
        self.addCleanup(database_path.stop)
        database.init_db()
        self.store=SQLiteLocalSyncStore(SyncConfig())
        self.store._db_path=self.path
        self.remote=Mock()
        self.remote.is_online.return_value=False
        self.dal=HandheldSyncDataAccess(self.store,self.remote)
        schedule={'Schedule_ID':100,'Start_Date':'2026-11-11','Due_Date':'2026-11-12',
                  'Zone_Name':'Zone 1','Meter_Reader_ID':2,'Billing_Cycle':'2026-11'}
        self.store.cache_reading_schedules([schedule],2,'2026-11-01','2026-11-30')
        database.replace_consumers_from_sync([{'id':7,'meter_no':'MTR-7','name':'Isolated consumer',
            'zone_name':'Zone 1','previous_reading':100,'schedule_id':100,'is_read':False}])
        self.payload={'record_type':'meter_issue','is_flagged':True,'reading_id':str(uuid.uuid4()),
                      'consumer_id':7,'schedule_id':100,'meter_reader_id':2,'reading_date':'2026-11-11',
                      'exception':'Stuck Meter','meter_no':'MTR-7'}

    def test_offline_issue_survives_restart_without_changing_baseline_or_completing_reading(self):
        result=self.dal.saveMeterReading(self.payload)
        self.assertEqual(result['status'],'queued')
        reopened=SQLiteLocalSyncStore(SyncConfig())
        reopened._db_path=self.path
        self.assertEqual(reopened.list_pending()[0]['payload']['exception'],'Stuck Meter')
        self.assertEqual(float(database.get_consumer_by_id(7)['previous_reading']),100)
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM readings').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM local_billing_reference_reservations').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT is_read FROM reading_assignment').fetchone()[0],0)
        rows=database.get_zone_consumers_with_status('Zone 1',schedule_id=100)
        self.assertEqual(rows[0]['reading_status_label'],'Flagged: unable to read')
        self.assertFalse(rows[0]['is_read'])

    def test_report_syncs_once_and_does_not_block_an_actual_reading_after_repair(self):
        self.dal.saveMeterReading(self.payload)
        self.remote.is_online.return_value=True
        self.remote.save_reading_bundle.return_value={'meter_issue_report':{'sync_id':self.payload['reading_id']},'is_read':False,'bill':None}
        result=self.dal.syncPendingReadings()
        self.assertEqual((result['synced'],result['failed']),(1,0))
        self.remote.find_existing_reading.assert_not_called()
        self.remote.reserve_billing_reference.assert_not_called()
        self.assertEqual(self.dal.syncPendingReadings()['synced'],0)
        self.assertEqual(self.remote.save_reading_bundle.call_count,1)
        actual_id=str(uuid.uuid4())
        database.save_reading(7,110,10,reading_date='2026-11-12',schedule_id=100,sync_reading_id=actual_id)
        queued=self.dal.queueMeterReading({'consumer_id':7,'reading_id':actual_id,'reading_date':'2026-11-12',
            'schedule_id':100,'present_reading':110,'previous_reading':100,'consumption':10})
        self.assertEqual(queued['status'],'queued')
        self.assertEqual(database.get_meter_issue_reports(),[])

    def test_backend_client_sends_only_issue_fields_without_bill_or_fabricated_reading(self):
        client=BackendApiClient(SyncConfig(backend_api_base_url='https://isolated.example.test/api'))
        client._req=Mock(return_value=(200,{'meter_issue_report':{'sync_id':self.payload['reading_id']},'bill':None}))
        client.save_reading_bundle({**self.payload,'present_reading':0,'consumption':0,'billing_reference':'SLR2026000999'})
        args,kwargs=client._req.call_args
        self.assertEqual(args,('POST','/api/handheld/meter-issues'))
        for key in ('bill','billing_reference','present_reading','consumption'):
            self.assertNotIn(key,kwargs['payload'])
        self.assertEqual(kwargs['payload']['issue_reason'],'Stuck Meter')

    def test_legacy_flagged_queue_keeps_reference_and_uploads_report_instead_of_bill(self):
        draft=self.store.get_or_create_bill_reservation(7,'2026-11-11',schedule_id=100)
        self.store.save_reserved_reference(draft['bill_sync_id'],'SLR2026000999')
        legacy={**self.payload,'reading_id':draft['reading_sync_id'],'bill_sync_id':draft['bill_sync_id'],
                'billing_reference':'SLR2026000999','present_reading':100,'consumption':0}
        legacy.pop('record_type')
        queued=self.store.enqueue_operation('create',legacy,backend_status='pending')
        self.store.mark_needs_review(queued['id'],'Reading captured outside its assigned schedule dates.')
        self.dal.reconcileScheduleReadings()
        self.remote.is_online.return_value=True
        self.remote.save_reading_bundle.return_value={'meter_issue_report':{'sync_id':legacy['reading_id']},'bill':None}
        self.assertEqual(self.dal.syncPendingReadings()['synced'],1)
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT status FROM local_billing_reference_reservations').fetchone()[0],'Reserved')
            original=conn.execute('SELECT payload FROM sync_queue_meter_readings').fetchone()[0]
            self.assertIn('SLR2026000999',original)
        replacement=self.store.get_or_create_bill_reservation(7,'2026-11-11',schedule_id=100)
        self.assertNotEqual(replacement['reading_sync_id'],legacy['reading_id'])

    def test_issue_action_requires_no_present_reading_rates_or_printer(self):
        class InlineThread:
            def __init__(self,target,**kwargs):self.target=target
            def start(self):self.target()
        dal=SimpleNamespace(saveMeterReading=Mock(return_value={'status':'queued'}))
        view=SimpleNamespace(_operation_busy=False,_consumer={'id':7,'meter_no':'MTR-7'},
            _selected_exception='Stuck Meter',_sync_dal=dal,_meter_reader_account_id=2,
            _schedule_for_consumer=lambda _: {'scheduleId':100,'startDate':'2026-11-11','dueDate':'2026-11-12','billingMonth':'2026-11'},
            _set_operation_busy=Mock(),meterIssueSaveFinished=SimpleNamespace(emit=Mock()),alertRequested=SimpleNamespace(emit=Mock()))
        with patch('src.qt_hybrid_app.manila_current_date',return_value=date(2026,11,11)),patch('src.qt_hybrid_app.threading.Thread',InlineThread):
            AppBridge.saveMeterIssue(view)
        sent=dal.saveMeterReading.call_args.args[0]
        self.assertEqual(sent['exception'],'Stuck Meter')
        for key in ('present_reading','consumption','bill_sync_id','billing_reference'):
            self.assertNotIn(key,sent)
        self.assertTrue(view.meterIssueSaveFinished.emit.call_args.args[0]['success'])

    def test_high_usage_alone_stays_a_billable_actual_reading(self):
        normalized=self.dal._normalize_reading({'consumer_id':7,'consumption':600,'is_flagged':False,'exception':'None'})
        self.assertNotEqual(normalized.get('record_type'),'meter_issue')

    def test_legacy_flag_does_not_advance_baseline_or_count_as_read_after_offline_restart(self):
        database.save_reading(7,0,0,exception='Stuck Meter',is_flagged=True,
                              reading_date='2026-11-11',schedule_id=100,sync_reading_id=str(uuid.uuid4()))
        with self.store._connect() as conn:
            conn.execute("UPDATE reading_assignment SET is_read=1,reading_status='valid'")
            conn.commit()
        database.init_db()
        self.assertEqual(float(database.get_consumer_by_id(7)['previous_reading']),100)
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT is_read FROM reading_assignment').fetchone()[0],0)

    def test_an_earlier_same_day_reading_does_not_hide_a_new_meter_issue(self):
        database.save_reading(7,110,10,reading_date='2026-11-11',schedule_id=100,
            captured_at='2026-11-11T08:00:00+08:00')
        self.dal.saveMeterReading({**self.payload,'captured_at':'2026-11-11T09:00:00+08:00'})
        self.assertEqual(len(database.get_meter_issue_reports()),1)

    def test_unissued_legacy_issue_draft_cannot_become_a_future_billing_baseline(self):
        legacy={**self.payload,'bill_sync_id':'old-unissued-draft','billing_reference':'SLR2026000999'}
        self.dal.saveMeterReading(legacy)
        self.store.cache_consumers([{'id':7,'meter_no':'MTR-7','name':'Isolated consumer','zone_name':'Zone 1','previous_reading':100}])
        self.dal.cacheLocalBill(7,{'sync_id':'old-unissued-draft','current_reading':0,'date_covered_to':'2026-11-11'})
        context=self.dal.getCachedConsumerContext(7)
        self.assertFalse(context.get('local_bill'))
        self.assertEqual(context.get('local_bills'),[])
        self.assertEqual(self.store.load_cached_consumer_context(7)['local_bill']['sync_id'],'old-unissued-draft')


if __name__=='__main__':unittest.main()

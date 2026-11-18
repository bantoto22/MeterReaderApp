"""Verified resolution of held uploads without deleting saved field evidence."""
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


def _month(value):
    text=str(value or '').strip()
    if re.match(r'^\d{4}-(0[1-9]|1[0-2])(?:$|-)',text):
        return text[:7]
    for pattern in ('%B %Y','%b %Y'):
        try:return datetime.strptime(text,pattern).strftime('%Y-%m')
        except ValueError:pass
    return ''


def _number(value):
    try:
        number=Decimal(str(value))
        if number.is_finite():return format(number.normalize(),'f')
    except (InvalidOperation,ValueError,TypeError):pass
    raise ValueError('A saved reading value is missing. Keep this entry for office review.')


class ReviewQueue:
    def __init__(self,local,remote,is_duplicate,is_issue,audit,update_state,refresh_baseline,is_initial_baseline=None):
        self.local,self.remote=local,remote
        self.is_duplicate,self.is_issue=is_duplicate,is_issue
        self.audit,self.update_state=audit,update_state
        self.refresh_baseline=refresh_baseline
        self.is_initial_baseline=is_initial_baseline
        self.checked={}

    def entries(self,archived=False):
        loader=getattr(self.local,'list_archived_reviews',None) if archived else self.local.list_needs_review
        rows=loader() if callable(loader) else []
        result=[]
        for row in rows:
            payload=row['payload']
            checked=self.checked.get(row['id'],{})
            proof=row.get('review_server_record') if archived else checked.get('office')
            result.append({'id':row['id'],'consumer_id':payload.get('consumer_id'),
                'schedule_id':payload.get('schedule_id'),'reading_date':payload.get('reading_date'),
                'previous':payload.get('previous_reading'),'present':payload.get('present_reading',payload.get('current_reading')),
                'consumption':payload.get('consumption'),'reference':payload.get('billing_reference') or 'No reference',
                'reason':row.get('last_error') or row.get('conflict_reason') or '',
                'archived':archived,'reviewed_at':row.get('reviewed_at') or '',
                'office':proof or {},'token':checked.get('token') or '',
                'can_resolve':bool(checked),'action':checked.get('action') or 'archive',
                'values_differ':checked.get('values_differ',False)})
        return result

    def check(self,queue_id):
        self.checked.pop(queue_id,None)
        row=next((row for row in self.local.list_needs_review() if row['id']==queue_id),None)
        if not row:raise ValueError('This entry is no longer in Needs review. Refresh the list.')
        payload=row['payload']
        reason=str(row.get('last_error') or row.get('conflict_reason') or '')
        baseline_hold=bool(self.is_initial_baseline and self.is_initial_baseline(reason)
                           and payload.get('previous_reading') in (None,''))
        if self.is_issue(payload) or not (self.is_duplicate(reason) or baseline_hold):
            raise ValueError('This is not a confirmed duplicate. Keep it saved for office review.')
        current_reader=getattr(self.remote,'_meter_reader_id',None)
        if isinstance(current_reader,int) and str(payload.get('meter_reader_id'))!=str(current_reader):
            raise PermissionError('Log in as the original reader before resolving this entry.')
        if not self.remote or not self.remote.is_online():
            raise ConnectionError('Connect to the office backend before checking or archiving a duplicate.')
        reason_month=re.search(r'\b(\d{4}-(?:0[1-9]|1[0-2]))\b',reason)
        cycle=(reason_month.group(1) if reason_month else '') or _month(payload.get('billing_cycle')) or _month(payload.get('reading_date'))
        if not cycle:raise ValueError('The billing month is missing. Keep this entry for office review.')
        bill_duplicate='already has a bill for' in reason.lower() or baseline_hold
        saved=self.remote.find_existing_reading(payload['consumer_id'],payload['reading_date'],billing_cycle=cycle,include_bill_month=bill_duplicate)
        if not isinstance(saved,dict) or not saved.get('reading_id'):
            raise ValueError('No matching office reading was found. This entry remains saved for review.')
        if str(saved.get('consumer_id'))!=str(payload['consumer_id']) or saved.get('billing_cycle')!=cycle:
            raise ValueError('The office record belongs to another account or billing month. Nothing was archived.')
        bill=saved.get('bill') or {}
        if any(key not in saved for key in ('previous_reading','present_reading','consumption','reading_date','bill')):
            raise ValueError('Office comparison details are unavailable. Restart the updated backend, then check again.')
        if bill_duplicate and (not bill.get('bill_id') or bill.get('bill_month')!=cycle):
            raise ValueError('No active office bill for this month was confirmed. Keep this entry for office review.')
        state=str(saved.get('reading_status') or '').strip().lower()
        if state not in {'recorded','normal','verified','approved'} and not (
                state=='pending' and bill.get('bill_id') and str(saved.get('sync_status')).lower()=='synced'):
            raise ValueError('The office reading is not confirmed as usable. Keep this entry for review.')
        office={'consumer_id':saved['consumer_id'],'billing_cycle':cycle,'reading_id':saved['reading_id'],
            'sync_id':str(saved.get('sync_id') or ''),'reading_status':saved.get('reading_status'),
            'reading_date':str(saved.get('reading_date') or '')[:10],
            'previous':_number(saved.get('previous_reading')),'present':_number(saved.get('present_reading')),
            'consumption':_number(saved.get('consumption')),'updated_at':str(saved.get('updated_at') or ''),
            'bill_id':bill.get('bill_id'),'bill_sync_id':str(bill.get('sync_id') or ''),
            'reference':str(bill.get('billing_reference') or 'No bill issued')}
        if baseline_hold:
            # An office-created first bill can supersede a held capture whose
            # previous value was unknown. Keep the unknown value in History;
            # require matching values before retiring this case. The billing
            # cycle was verified above; capture dates may differ from bill dates.
            if (not bill.get('status') or str(bill['status']).strip().lower() in {'cancelled','canceled','void','voided','rejected'}
                    or office['previous']!='0'
                    or _number(payload.get('present_reading',payload.get('current_reading')))!=office['present']
                    or _number(payload.get('consumption'))!=office['consumption']):
                raise ValueError('The office bill differs from the held first reading. Keep this entry for office review.')
            context=self.remote.get_consumer_context(payload['consumer_id'],include_today=True)
            if (not isinstance(context,dict) or str(context.get('id',context.get('consumer_id')))!=str(payload['consumer_id'])
                    or not payload.get('meter_no') or str(context.get('meter_no'))!=str(payload['meter_no'])):
                raise ValueError('The original meter could not be confirmed. Keep this entry for office review.')
        differs=baseline_hold or str(payload.get('reading_date'))[:10]!=office['reading_date'] or any(left!=right for left,right in (
            (_number(payload.get('previous_reading')),office['previous']),
            (_number(payload.get('present_reading',payload.get('current_reading'))),office['present']),
            (_number(payload.get('consumption')),office['consumption'])))
        action='archive'
        same_bill=not payload.get('bill_sync_id') or (
            office['bill_sync_id']==str(payload['bill_sync_id']) and office['reference']==str(payload.get('billing_reference')))
        if office['sync_id']==str(payload.get('reading_id')) and not differs and same_bill:
            action='confirm_synced'
        token=hashlib.sha256(json.dumps(office,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.checked[queue_id]={'office':office,'token':token,'payload':payload,'action':action,'values_differ':differs}
        return self.checked[queue_id]

    def resolve(self,queue_id,expected_token):
        previous=self.checked.get(queue_id)
        if not previous or not expected_token or previous['token']!=expected_token:
            raise ValueError('Check the office record before resolving this entry.')
        verified=self.check(queue_id)
        if verified['token']!=expected_token or verified['payload']!=previous['payload']:
            self.checked.pop(queue_id,None)
            raise ValueError('The saved entry or office record changed. Check it again before resolving.')
        payload,office=verified['payload'],verified['office']
        if verified['action']=='confirm_synced':
            response={'meterreading':{'reading_id':office['reading_id'],'sync_id':office['sync_id'],
                'reading_status':office['reading_status'],'sync_status':'synced'},
                'bill':{'bill_id':office['bill_id'],'sync_id':office['bill_sync_id'],'billing_reference':office['reference']}}
            self.local.mark_target_synced(queue_id,'backend',response)
            self.update_state(payload.get('reading_id'),'synced',office['reading_status'])
            if payload.get('bill_sync_id') and office.get('bill_id'):
                self.local.mark_bill_reservation_used(payload['bill_sync_id'],office['bill_id'])
            status='synced'
        else:
            self.refresh_baseline(payload)
            self.local.archive_review_duplicate(queue_id,payload,office)
            self.update_state(payload.get('reading_id'),'archived','rejected')
            self.local.confirm_office_cycle(office)
            status='archived'
        self.audit(queue_id,status,'Reviewed against office record; original field evidence and references retained.',
                   {'reading':payload,'office':office})
        self.checked.pop(queue_id,None)
        return status

    def restore(self,queue_id):
        payload=self.local.restore_archived_review(queue_id)
        self.checked.pop(queue_id,None)
        self.update_state(payload.get('reading_id'),'needs_review','rejected')
        self.audit(queue_id,'needs_review','Restored archived duplicate for review; it has not been queued for upload.',payload)

"""Clear Needs review entries on this device, with a verified database backup.

Close the app first. Preview is read-only; --apply removes review queue entries,
retires their local readings and unused references, and preserves printed history.
This command has no network access and never changes office records.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
import sys
import uuid


def _columns(conn, table):
    return {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}


def _snapshot(conn):
    required = {
        'sync_queue_meter_readings': {'id', 'reading_id', 'consumer_id', 'payload', 'backend_status'},
        'readings': {'id', 'consumer_id', 'sync_reading_id', 'reading_status', 'reading_sync_status',
                     'schedule_id', 'reading_date', 'present_reading', 'is_flagged'},
        'consumers': {'id', 'previous_reading', 'latest_reading', 'latest_reading_date'},
        'local_billing_reference_reservations': {'bill_sync_id', 'reading_sync_id', 'status', 'bill_id', 'used_at'},
    }
    for table, columns in required.items():
        if not columns <= _columns(conn, table):
            raise ValueError(f'Cannot safely inspect {table}; required columns are missing.')
    rows = [dict(row) for row in conn.execute(
        "SELECT * FROM sync_queue_meter_readings WHERE backend_status='needs_review' ORDER BY id")]
    for row in rows:
        payload = json.loads(row['payload'])
        if (not isinstance(payload, dict) or not row['reading_id']
                or str(payload.get('reading_id')) != str(row['reading_id'])
                or str(payload.get('consumer_id')) != str(row['consumer_id'])):
            raise ValueError('A review entry has inconsistent identifiers; nothing was cleared.')
    return rows


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _clear(conn, rows):
    removed = retired = 0
    affected = {}
    bill_ids = set()
    reading_ids = set()
    for row in rows:
        payload = json.loads(row['payload'])
        # Another operation for the same reading remains authoritative.
        shared = conn.execute("""SELECT 1 FROM sync_queue_meter_readings
            WHERE reading_id=? AND backend_status<>'needs_review' LIMIT 1""", (row['reading_id'],)).fetchone()
        readings = [dict(r) for r in conn.execute(
            'SELECT * FROM readings WHERE sync_reading_id=? AND consumer_id=?',
            (row['reading_id'], row['consumer_id']))]
        if not shared and not any(str(r['reading_sync_status']).lower() == 'synced' for r in readings):
            reading_ids.add(row['reading_id'])
            if payload.get('bill_sync_id'):
                bill_ids.add(str(payload['bill_sync_id']))
            affected.setdefault(row['consumer_id'], []).append({'id': row['id'], **payload})
            for reading in readings:
                retired += conn.execute("""UPDATE readings SET reading_status='deleted',
                    reading_sync_status='archived' WHERE id=?""", (reading['id'],)).rowcount
                affected.setdefault(row['consumer_id'], []).append({**payload, **reading})
        removed += conn.execute("DELETE FROM sync_queue_meter_readings WHERE id=? AND backend_status='needs_review'",
                                (row['id'],)).rowcount

    protected_bill_ids = set()
    for row in conn.execute('SELECT payload FROM sync_queue_meter_readings'):
        payload = json.loads(row['payload'])
        if payload.get('bill_sync_id'):
            protected_bill_ids.add(str(payload['bill_sync_id']))
    bill_ids.difference_update(protected_bill_ids)

    # Keep every allocated reference, but prevent a cleared reading from reusing
    # its old reservation, even when it is captured again on the same day.
    for row in conn.execute('SELECT * FROM local_billing_reference_reservations').fetchall():
        if row['bill_sync_id'] not in bill_ids and row['reading_sync_id'] not in reading_ids:
            continue
        if row['bill_sync_id'] in protected_bill_ids:
            continue
        if row['status'] in ('Pending', 'Reserved') and row['bill_id'] is None and row['used_at'] is None:
            conn.execute("UPDATE local_billing_reference_reservations SET status='Discarded' WHERE bill_sync_id=?",
                         (row['bill_sync_id'],))

    context_columns = _columns(conn, 'handheld_consumer_context_cache')
    if {'consumer_id', 'context_json'} <= context_columns:
        for row in conn.execute('SELECT consumer_id,context_json FROM handheld_consumer_context_cache').fetchall():
            if row['consumer_id'] not in affected or row['context_json'] in (None, ''):
                continue
            context = json.loads(row['context_json'])
            if not isinstance(context, dict):
                raise ValueError('Invalid cached consumer context; changes rolled back.')
            old = json.dumps(context, sort_keys=True)
            if str((context.get('local_bill') or {}).get('sync_id') or '') in bill_ids:
                context.pop('local_bill')
            if 'local_bills' in context:
                context['local_bills'] = [bill for bill in context['local_bills']
                                         if str(bill.get('sync_id') or '') not in bill_ids]
            if json.dumps(context, sort_keys=True) != old:
                conn.execute('UPDATE handheld_consumer_context_cache SET context_json=? WHERE consumer_id=?',
                             (json.dumps(context), row['consumer_id']))

    for consumer_id, discarded in affected.items():
        consumer = conn.execute('SELECT * FROM consumers WHERE id=?', (consumer_id,)).fetchone()
        valid = [dict(row) for row in conn.execute("""SELECT * FROM readings WHERE consumer_id=?
            AND COALESCE(is_flagged,0)=0 AND lower(reading_status) NOT IN ('deleted','rejected','flagged','invalid')
            ORDER BY date(reading_date) DESC,id DESC""", (consumer_id,))]
        baseline_is_discarded = consumer and any(_finite(row.get('present_reading')) is not None
            and _finite(consumer['previous_reading']) == _finite(row.get('present_reading')) for row in discarded)
        latest_is_discarded = consumer and any(_finite(row.get('present_reading')) is not None
            and _finite(consumer['latest_reading']) == _finite(row.get('present_reading'))
            and str(consumer['latest_reading_date'] or '')[:10] == str(row['reading_date'])[:10]
            for row in discarded)
        # save_reading also updates latest_reading, so that field alone is not
        # evidence that the office accepted a discarded local reading.
        if baseline_is_discarded or latest_is_discarded:
            baseline = _finite(valid[0]['present_reading']) if valid else None
            baseline_date = valid[0]['reading_date'] if valid else None
            office = None if latest_is_discarded else _finite(consumer['latest_reading'])
            office_date = str(consumer['latest_reading_date'] or '')[:10] if consumer else ''
            if office is not None and (not valid or office_date > str(valid[0]['reading_date'])[:10]
                                      or (office_date == str(valid[0]['reading_date'])[:10]
                                          and str(valid[0]['reading_sync_status']).lower() == 'synced')):
                baseline = office
                baseline_date = consumer['latest_reading_date']
            if baseline is None:
                earliest = min(discarded, key=lambda row: (str(row['reading_date']), row['id']))
                baseline = _finite(earliest.get('previous_reading'))
                baseline_date = earliest.get('previous_reading_date')
            if baseline is None:
                raise ValueError('The prior meter baseline is unavailable; nothing was cleared. Sync first.')
            previous = baseline if baseline_is_discarded else consumer['previous_reading']
            latest = baseline if latest_is_discarded else consumer['latest_reading']
            latest_date = baseline_date if latest_is_discarded else consumer['latest_reading_date']
            conn.execute('UPDATE consumers SET previous_reading=?,latest_reading=?,latest_reading_date=? WHERE id=?',
                         (previous, latest, latest_date, consumer_id))
            if {'id', 'previous_reading', 'latest_reading', 'latest_reading_date'} <= _columns(conn, 'handheld_consumers_cache'):
                conn.execute('UPDATE handheld_consumers_cache SET previous_reading=?,latest_reading=?,latest_reading_date=? WHERE id=?',
                             (previous, latest, latest_date, consumer_id))

        for schedule_id in {row['schedule_id'] for row in discarded if row.get('schedule_id') is not None}:
            remaining = next((row for row in valid if row['schedule_id'] == schedule_id), None)
            if remaining is None:
                for queued in conn.execute("""SELECT payload,backend_status FROM sync_queue_meter_readings
                        WHERE consumer_id=? AND backend_status IN ('pending','failed','synced') ORDER BY id DESC""",
                        (consumer_id,)):
                    payload = json.loads(queued['payload'])
                    if str(payload.get('schedule_id')) == str(schedule_id):
                        remaining = {'reading_status': payload.get('reading_status') or 'valid',
                                     'reading_sync_status': queued['backend_status']}
                        break
            for table in ('reading_assignment', 'handheld_assignments_cache'):
                if not {'consumer_id', 'schedule_id', 'is_read', 'reading_status', 'reading_sync_status'} <= _columns(conn, table):
                    continue
                if remaining:
                    conn.execute(f"""UPDATE {table} SET is_read=1,reading_status=?,reading_sync_status=?
                        WHERE consumer_id=? AND schedule_id=?""",
                        (remaining['reading_status'], remaining['reading_sync_status'], consumer_id, schedule_id))
                else:
                    conn.execute(f"""UPDATE {table} SET is_read=0,reading_status='pending',reading_sync_status='pending'
                        WHERE consumer_id=? AND schedule_id=? AND lower(reading_sync_status)<>'synced'""",
                        (consumer_id, schedule_id))
    return removed, retired


def cleanup_reviews(db_path, *, apply=False):
    path = Path(db_path).resolve(strict=True)
    conn = sqlite3.connect(path.as_uri() + ('?mode=rw' if apply else '?mode=ro'), uri=True, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        rows = _snapshot(conn)
        report = {'database': str(path), 'needs_review': len(rows), 'applied': False,
                  'removed': 0, 'retired_local_readings': 0, 'backup': None}
        if not apply or not rows:
            return report
        directory = path.parent / 'backups'
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
        backup_path = directory / f'{path.stem}-before-review-cleanup-{stamp}-{uuid.uuid4().hex[:8]}.db'
        backup = sqlite3.connect(backup_path)
        try:
            backup.row_factory = sqlite3.Row
            conn.backup(backup)
            if backup.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or _snapshot(backup) != rows:
                raise ValueError('The database changed or the backup could not be verified; retry with the app closed.')
        finally:
            backup.close()
        conn.execute('BEGIN IMMEDIATE')
        if _snapshot(conn) != rows:
            raise ValueError('Review entries changed during backup; retry with the app closed.')
        removed, retired = _clear(conn, rows)
        if removed != len(rows) or _snapshot(conn):
            raise ValueError('Cleanup counts did not reconcile; changes rolled back.')
        if {'queue_id', 'status', 'message', 'payload'} <= _columns(conn, 'sync_audit_log'):
            conn.execute('INSERT INTO sync_audit_log(queue_id,status,message,payload) VALUES(NULL,?,?,?)',
                         ('maintenance', f'User-requested cleanup removed {removed} Needs review entries.',
                          json.dumps({'queue_ids': [row['id'] for row in rows], 'backup': str(backup_path)})))
        conn.commit()
        report.update(applied=True, removed=removed, retired_local_readings=retired,
                      needs_review=0, backup=str(backup_path))
        return report
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=Path(__file__).resolve().parent.parent / 'data' / 'meter.db')
    parser.add_argument('--apply', action='store_true', help='Back up and clear Needs review entries on this device.')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(cleanup_reviews(args.db, apply=args.apply), indent=2))
    except (OSError, ValueError, TypeError, AttributeError, sqlite3.Error) as exc:
        print(f'Cleanup stopped: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

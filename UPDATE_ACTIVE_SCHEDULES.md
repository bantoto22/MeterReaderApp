# Meter issue, active schedule and sync update - November 18, 2026

Install this update together with the matching San Lorenzo backend changes.
Close the device app, copy the supplied files into its MeterReaderApp folder,
and reopen the app. Keep the existing `.env`, SQLite database, and data folder.

The current package is `updates/MeterReaderApp-empty-sync-reporting-2026-11-18.zip`.
This includes the previous sync recovery changes and clearer empty-download
results. **No Assigned Consumers** means the backend returned no consumer rows
for the displayed reader and dates. Check the schedule's assigned count and
billing cycle in the main system. A new schedule for a consumer already read in
that billing cycle has no new reading work; local review cleanup does not clear
the office reading. A malformed backend response must show a download error.
With no new assignments, sync still refreshes cached consumer details for the
signed-in reader. Verify a changed office bill/payment appears in the cached
details and **Offline records** shows a download even when **Pulled** is zero.
After installing, check recovery without restarting the app:

- With automatic sync enabled, interrupt connectivity during a download and
  restore it. A failed download retries after 30 seconds, backing off to at most
  five minutes on repeated failure. Backend recovery is checked even if Wi-Fi
  stays connected. A successful pull shows **Fresh backend data**.
- Create another assignment in the office while the app remains open, then tap
  **Settings -> Sync Now**. Confirm the new assignment appears. An upload error
  must still allow the download stage to run, with the upload problem reported.
- Retry queued readings after connectivity returns. Confirm the original saved
  reading IDs and references are retained and only accepted entries become
  synced. A global API outage must not cause one timeout per queued reading.
- If the backend rejects the online session, sign in online again. Local field
  work remains available; restarting the device is not an authentication step.

1. In the main system, create a current or future reading schedule and assign
   the intended reader and concessionaires. Existing expired schedules are no
   longer offered for new device readings. The cleanup removed 160 unused
   overdue schedules and retained 83 historical schedules. Assign fresh work
   before expecting consumers in the active route list.
2. On the device, open **Settings -> Sync Now**. The route list should show
   current/upcoming schedules only. Old unread schedules must not reappear in
   another route or in Past schedules.
3. An imported account assigned to a new schedule should use that schedule's
   billing month and its last imported meter reading. Its historical bill month
   must not replace the assignment's billing cycle. A reading already completed
   in that billing month remains completed.
4. Tap **Settings -> Sync Now** to automatically clear extra entries whose account
   and billing month already have a usable office reading or bill. This includes
   old **Needs review** and duplicate-failure entries. The existing office record
   wins; the extra entry is archived without uploading or issuing another bill.
   The result shows **Duplicates ignored**. Its original IDs, values, and reserved
   reference remain in **Settings -> Review history -> History**. Reserved numbers
   are never recycled. A repeat sync must leave the duplicate archived.
   The current office meter baseline is refreshed before an extra reading is
   archived, and genuine newer offline work remains intact. Unconfirmed duplicates,
   unreadable-meter reports and unrelated schedule problems are not discarded.
   History provides **Restore to review** for an entry that needs office follow-up;
   restoring does not upload it or automatically archive it again.
5. Record a valid reading offline while its schedule is active, restart the app,
   then reconnect and sync. It must upload once even if the deadline has since
   passed. Repeat Sync Now: there must be no second backend reading or bill.
6. Expired assignments must not request new offline billing references. Existing
   reserved references remain unchanged, including those attached to held work.
7. For an unreadable meter, choose its problem from the issue dropdown. The
   action becomes **Save Meter Issue**; a present reading, billing rates, and a
   printer are not required. The report is stored offline and synced without
   generating a bill. It does not advance the previous reading or count as read.
8. Billing staff can open **Scheduling, Zones & Devices -> Unreadable meters -> Refresh** in
   the main system. After repair, choose **None** on the device and capture an
   actual reading. That valid reading can generate a bill and resolve the issue.

`Flagged` means an unreadable meter. These observations now use the dedicated
meter-issue endpoint, not the reading-and-bill endpoint. Legacy flagged payloads
retain their IDs, references and original evidence, but upload as issue reports.
Issue reports can sync after their old assignment expired; that does not create
an overdue reading or complete a billing cycle. Genuine actual readings captured
outside their assignment dates still need review. High consumption by itself
is a warning, not an unreadable-meter report.

Network failures, expired online authentication, and unconfirmed reference
conflicts still appear as real problems. This update does not erase saved
readings or mark unaccepted readings as successfully uploaded.

The Windows checks use disposable SQLite and private PostgreSQL data. They cover
offline issue storage/restart/upload, no bill or fabricated reading for an issue,
actual billing after repair, preserved historical references, and retry safety.
The pre-cleanup backup was restored and its cleanup rehearsed on private PostgreSQL.
They do not establish Raspberry Pi deployment, Wi-Fi reliability, or physical
printer behavior. Confirm the checks above on the actual device after copying.

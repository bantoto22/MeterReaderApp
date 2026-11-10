# Meter issue, active schedule and sync update - November 11, 2026

Install this update together with the matching San Lorenzo backend changes.
Close the device app, copy the supplied files into its MeterReaderApp folder,
and reopen the app. Keep the existing `.env`, SQLite database, and data folder.

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
4. Confirmed duplicate readings and captures outside their schedule dates move
   to **Needs review**. Their original IDs, readings, and billing references are
   retained. They no longer repeatedly fail uploads or prevent other queued
   readings from syncing. Settings shows the consumer, schedule, reference and
   saved reason. Reviewing/resolving the business discrepancy is still manual;
   this package does not add a button to discard or approve saved readings.
5. Record a valid reading offline while its schedule is active, restart the app,
   then reconnect and sync. It must upload once even if the deadline has since
   passed. Repeat Sync Now: there must be no second backend reading or bill.
6. Expired assignments must not request new offline billing references. Existing
   reserved references remain unchanged, including those attached to held work.
7. For an unreadable meter, choose its problem from the issue dropdown. The
   action becomes **Save Meter Issue**; a present reading, billing rates, and a
   printer are not required. The report is stored offline and synced without
   generating a bill. It does not advance the previous reading or count as read.
8. Billing staff can open **Meter Reading -> Unreadable meters -> Refresh** in
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

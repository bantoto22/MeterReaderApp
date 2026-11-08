# Water Meter Reader

A handheld device application for field meter reading with receipt printing.

## Folder Structure

```
Meter_Reader/
├── assets/
│   ├── images/         # PNG image files (logo, icons)
│   └── fonts/          # Montserrat.ttf font file
├── src/
│   ├── meter_reader.py # Main application entry
│   ├── database.py     # SQLite database operations
│   └── receipt.py      # Receipt generation
├── data/
│   └── meter.db        # SQLite database file
├── main.py             # Launcher script
└── README.md
```

## How to Run

```bash
python main.py
```

### Qt Hybrid Mode (Widgets + QML overview)

```bash
python main.py
```

Install dependency first on development PCs:

```bash
pip install PySide6
```

On Raspberry Pi OS Trixie `armhf`, use PyQt6 from `apt` instead of PySide6:

```bash
sudo apt update

sudo apt install -y \
python3-pyqt6 \
python3-pyqt6.qtqml \
python3-pyqt6.qtquick \
qml6-module-qtquick \
qml6-module-qtquick-controls \
qml6-module-qtquick-layouts \
qml6-module-qtqml-workerscript
```

Then run:

```bash
DISPLAY=:0 \
XAUTHORITY=/home/pi/.Xauthority \
python3 main.py
```

## Login

Use an active Meter Reader account from the backend. The device does not create
default accounts. The old `reader1` and `reader2` demo logins are no longer supported.

The first login requires a reachable backend. After a successful online login,
the same credentials work offline on that device. Connection failures use the
cached account; an explicit rejection of credentials or account access does not.

Device login sends `X-SLR-Client: handheld` with JSON credentials to `/api/login`.
The backend must return a session `token` for an active Meter Reader; the app
keeps it in memory and uses Bearer authentication for API calls and heartbeats.
Browser cookies and CSRF tokens are not device session tokens. Deploy the
matching backend login update, restart the backend, then update and restart the
Pi app and sign in online. Keep the Pi's existing `.env` and `data` directory.

## Features

- Zone-based meter reading
- Progress tracking
- Receipt printing
- User authentication (database-stored)
- Profile menu with logout

## Handheld Sync Flow + Environment Setup

The handheld sync layer lives in `src/handheld_sync.py` and is designed for:
- Online mode: HTTPS requests to the Node backend through Tailscale Funnel.
- Offline mode: local SQLite cache + `sync_queue_meter_readings`.
- PostgreSQL access: the Node backend is the only process that holds database credentials.
- Reconnect: the backend API queue flushes with conflict detection and audit logs.

The device normally works offline. After initial account and route provisioning,
readers use cached data and save readings on the device. Online sessions serve
data synchronization and presence reporting; their expiry does not close local
field work or discard readings.

### Environment

1. Copy `.env.example` to `.env`.
2. Set `BACKEND_API_BASE_URL=https://aspire.tail3de291.ts.net/api`.
3. Enable sync by setting `HANDHELD_SYNC_ENABLED=1`.

If sync is enabled and required env vars are missing, the sync layer raises a clear startup/config error.

### Local Storage

The handheld queue, sync audit log, and consumer cache are stored in the Pi's local SQLite database.
The device does not store third-party cloud keys or PostgreSQL credentials.

### Offline Operation

- Each meter reader must sign in online at least once so the device can cache a salted password hash and assigned route data.
- While offline, the reader can sign in, browse cached schedules and consumers, and record readings locally.
  Route sync reserves backend-issued billing references for every remaining reading day from each schedule's
  start through its deadline, within the downloaded assignment window. Expired unread schedules prepare today's
  reference. References remain in SQLite across restarts; each bill prints the same number it later uploads.
  If that reading date has no cached reference, the device still saves the reading and queues it for sync,
  but waits to print until it has the exact reference. It never prints a new receipt with `Billing Ref: N/A`.
- Offline readings remain in the local SQLite queue and upload automatically or through `Sync Now` when the backend API becomes reachable.
- An invalid or inactive account response from the backend is never bypassed with stale cached credentials.

### Tailscale Funnel

The device uses the same public HTTPS Funnel as the web app:

```text
Device -> https://aspire.tail3de291.ts.net/api -> Node backend:3001 -> PostgreSQL:5432
```

The app checks `https://aspire.tail3de291.ts.net/health` before uploading queued
readings. If the Pi reports the backend offline, run
`curl -fsS --max-time 10 https://aspire.tail3de291.ts.net/health` on the Pi and
inspect Sync Logs for the HTTP or network error. A failed health check does not
remove queued readings or cached consumer records. The app does not report an
upload failure when there are no queued readings.

Settings → Backend Logs also shows the current health-check failure when the
upload queue is empty. The app rechecks the backend after a Wi-Fi connection,
including when automatic sync is disabled.

If the Pi reaches the hostname but reports `SSL: UNEXPECTED_EOF_WHILE_READING`,
check the Funnel's public HTTPS path. On the backend host, confirm that
`tailscale funnel status` still shows `/ proxy http://127.0.0.1:3001`. If the
local backend health check succeeds but the public Funnel TLS handshake fails,
cycle only that Funnel route with `tailscale funnel --https=443 off` followed by
`tailscale funnel --bg 3001`, then repeat the Pi's `curl` check. This briefly
interrupts public access. An IPv6 `Network is unreachable` message is not the
cause when curl subsequently tries IPv4; check the final IPv4/TLS result.

### Wi-Fi connections on the Raspberry Pi

In Settings → Connectivity, scan and select a network. **Security** defaults to
**Automatic** and the app displays the detected security type. WPA/WPA2 Personal,
WPA3 Personal, and Open can also be selected explicitly. Enter the password for a
new secured network; leave Password blank to reuse a saved password. Open
networks do not require a password. WEP and enterprise networks require setup in
Raspberry Pi network settings.

The app matches saved profiles by their actual SSID and activates them by UUID,
so a renamed profile still works. It sets the required security key management
before connecting and supplies entered passwords through NetworkManager's
private temporary password file. Other network profiles are retained. These
commands follow the [NetworkManager nmcli reference](https://networkmanager.dev/docs/api/latest/nmcli.html).
Background scans preserve the selected network and its security information.

When updating the Pi, deploy the updated `src` and `assets/qml` directories
together, including `src/wifi.py`, and restart the app. Keep the device's `.env`
and `data` directory.

### Device provisioning and heartbeat

Provision each Raspberry Pi with its own permanent `HANDHELD_DEVICE_ID` in `.env`
(for example, `SLR-RPI-001`) and a friendly `SLR_DEVICE_LABEL` (for example,
`Reader Unit 01`). `SLR_DEVICE_ID` is accepted as an alternative to the existing
`HANDHELD_DEVICE_ID`; if both are set, they must match. Do not copy a provisioned
ID to another Pi. Keep the `.env` file across app updates. The ID accepts up to
120 letters, numbers, dots, hyphens, or underscores; the label accepts up to
200 characters. The app refuses to start if the ID or backend URL is missing.

After an online Meter Reader login, the app sends an authenticated device
heartbeat immediately and every 60 seconds, plus one when Wi-Fi reconnects.
It stops on logout or shutdown. A 401 response clears the online session and
pauses heartbeats while keeping local field work open. Online sign-in is required
again before syncing; heartbeat failures never discard queued readings.
The backend should show **Active** if a heartbeat arrived within the past
three minutes, **Inactive** after three minutes, and **No registered device**
before the first heartbeat. The device does not send a reader ID in the
heartbeat; the backend must associate it with the authenticated account.
The backend heartbeat endpoint and status display must be deployed separately
from this Raspberry Pi app.

### Billing-reference lifecycle

During route sync, the device persists stable reading
and bill UUIDs locally for each scheduled reading date, calls `POST /api/handheld/billing-references/reserve`, and stores the returned
`SLRYYYY######` reference. Timeouts reuse the same UUIDs. The reading-bundle upload sends that exact reference and
separate bill UUID. After the backend confirms the saved bill, the local reservation becomes `Used`; the printed
reference remains permanently assigned to that bill and is never reused. Reprints retain the original reference.
The backend binds each reservation to its bill date, so a reference for yesterday is never reassigned to
today's bill. Preparing future scheduled dates uses the same backend sequence and separate bill UUIDs.
Sync results report reference preparation failures; retry sync before leaving connectivity if any occur.

To clean old unused local reference reservations on the Pi, close the device app
and run these commands from the `MeterReaderApp` directory:

```bash
python3 src/offline_reference_cleanup.py
python3 src/offline_reference_cleanup.py --apply
```

The first command previews counts without changing the database. The second
verifies a full SQLite backup under `data/backups/`, rechecks links under a write
lock, and removes only unchanged unused `Pending`/`Reserved` reservations dated
before today in Asia/Manila. Current/future dates, used reservations, queued work
(including failed, conflict, review, and synced records), saved readings, receipts,
and cached bill references are retained. Unknown schema or invalid cached JSON
stops cleanup. The command reports the backup path and number removed; running it
again does not remove the protected records. Backend reservations and the shared
reference-number sequence are not reset, and old numbers are never reused.

### Handheld UI

- Sync badges are shown in Meter Entry: `Online`, `Offline`, `Pending Sync`, `Sync Failed`.
- Pending count is displayed.
- `Sync Now` triggers manual queue flush.

### Schedule-assignment API contract

To keep missed readings available, `/api/handheld/consumers` must return one row per
consumer assignment with `consumer_id`, the complete text `acct_no`,
`assignment_order`, `schedule_id`, `reading_route_id`, `schedule_date`,
`schedule_due_date`, `billing_cycle`, `zone_name`, `is_read`, `reading_status`, and
`reading_sync_status`. Account numbers must be returned without numeric coercion or
segment rewriting (for example `02-11-152-0` and `02-11-152-A1`). The endpoint must
include unread assignments after their due
date and must not treat a schedule status change as completion.

Reading-bundle requests carry `consumer_id`, `schedule_id`, `reading_route_id`,
`assignment_order`, the same schedule fields, and `captured_at`. The account number
is included for identification only and is not the reading's database key. The
backend must persist `schedule_id` on the meter reading, accept a valid late
reading, and clear reader/biller exceptions only after that reading is committed.
Rejected or deleted readings must leave the assignment pending.

The Billing Officer sets `reading_schedule.payment_due_date` when saving an
assignment. The device caches it as `schedule_payment_due_date` and may show it
for an unissued reading. `schedule_due_date` is only the assignment End Date.
The form and unissued preview look up the payment date by the selected
`schedule_id` in the refreshed local schedule cache, so a newer schedule date
replaces an older date copied into a consumer assignment. An issued bill keeps
the due date returned by the backend.
For older assignments without a payment date, the Node backend uses
`admin_settings.due_date_days`. The device does not calculate the fallback.

The backend owns issued bills' payment due dates, penalty rates, previous
penalties, current penalties, totals, status, and setting IDs. The device sends
reading and base charge data to `/api/handheld/reading-bundles` without those
final fields. An issued bill keeps its saved due date and penalty rate even if
the assignment or Admin Settings change later.

An offline reading is queued in SQLite for later API sync. The device immediately
shows a local receipt estimate from its cached tariff, unpaid-bill records, and
the linked schedule's Payment Due Date (or cached `due_days` fallback). It saves
that receipt for offline reprint across restarts. On successful sync, the returned
`response.bill` is saved unchanged in the sync record and its values are mirrored
into the local consumer cache. If an unpaid backend bill unexpectedly returns
zero totals, the device keeps its nonzero local receipt and flags the mismatch;
the backend bill still needs investigation. The returned `billing_policy` source,
payment date, fallback days, and late fee are retained for diagnostics; they
never recalculate a saved backend bill. Automatic sync and reconnection refresh
`/api/handheld/consumers/:id/context`; opening a consumer or receipt reads the
SQLite snapshot without a separate network request.

The locally calculated bill is also kept in SQLite under its reserved bill sync
ID, separate from the backend bill. It can be used for offline reprints and as
the prior balance of a later offline reading when the last backend total is
missing or zero. A complete backend bill takes precedence when it arrives.

Before generating a receipt, the device validates the coverage dates on the
specific bill selected for printing. Both dates must be valid calendar dates,
and the start must not be later than the end. Invalid coverage holds printing
for review while retaining the saved reading and exact billing reference.
Cached bill reprints use the same validation; a penalty refresh with invalid
coverage retains the previously saved receipt. See [Device smoke test](DEVICE_SMOKE_TEST.md)
for the checks to perform on the Raspberry Pi after deploying an update.

During each assigned-consumer pull, a bounded background refresh requests that
same authenticated context endpoint for each assigned consumer before the app
reports the pull complete. SQLite keeps the
bill and any `unpaid_bills`, `payments`, `payment_history`, `readings`, or
`reading_history` records returned by the API, plus the latest reading dates.
The newest API response replaces current bill and unpaid-bill snapshots. Payment
and reading history is merged by record ID and retains the newest 15 records of
each type, removing the oldest one as each new record exceeds that limit.
Offline lookups use the last successful response. The device cannot fetch payment or reading history that
the backend does not expose through this endpoint.
Assignment refreshes also preserve the last cached meter reading, tariff, and
fees when an API response omits those fields, so reopening the app offline does
not reset them. Explicit replacement values, including zero fees, still update
the cache.

The assigned-consumer/context response and the authoritative `response.bill` must
also expose the concessionaire's `connection_fee_components` records. The device
maps component code `MTR` to **Water Meter Fee**, `CONN` to **Connection Fee**, and
`MEM` to **Membership Fee**. Flat `meter_maintenance_fee`, `connection_fee`, and
`membership_fee` bill fields remain supported. These fees are added to the amount
due, but they must never be included in either the current or carried penalty
base. The penalty base is the water-consumption charge only.

Schedules are grouped on the device only when meter reader, scheduled date, due
date, and billing cycle match. Each grouped route keeps its zone schedules and
their original IDs. “All zones” is a display filter only: consumer lookup,
deadline state, offline completion, and reading submission always use the
`schedule_id` belonging to the consumer's zone.

Expired schedules with unread assignments are also carried into the prioritized
active route automatically. They remain available under Past schedules, but the
reader does not need to open that selector to discover or process them. Carry-over
rows retain their expired schedule dates and original zone `schedule_id`.
Schedule refreshes also download cancelled schedules so an old offline cache cannot keep offering
them as active or overdue assignments. A reading already saved against a cancelled assignment is
retained in SQLite as **Needs review**, with its original reading ID, bill ID, and billing reference.
It is excluded from upload retries and the active failure count, so other readings can sync normally.
Settings shows the review count and saved references; Sync Logs retains the assignment details.
Before uploading queued readings or an online save, the device checks the backend's cancelled
schedules for the original reader and assignment dates. This handles stale offline schedule caches
on the first sync. A cancellation confirmed after an assignment rejection is handled the same way.
An assignment rejection without a confirmed cancellation remains an upload failure.
If a fresh backend schedule download confirms the original schedule has been restored for the same
reader, the original saved reading returns to the upload queue. The device never silently moves it
to a different schedule or marks it synced without backend acceptance.

Sync Now and automatic assignment refreshes use today's date in Asia/Manila to
download the past year and the current and next month of schedules. Viewing an
older route does not narrow discovery of new assignments. Automatic assignment
refresh runs every five minutes by default (`BACKEND_SYNC_INTERVAL_MS`, minimum
300000 ms); Sync Now downloads immediately without restarting the app. Download
failures are reported as pull warnings instead of counting cached records as a
successful download. Cached routes and queued readings remain available offline.
Settings and Diagnostics show whether the assignment download returned fresh
backend data or failed while cached records remain in use. A reachable health
endpoint does not hide a failed authenticated assignment download. Upload-only
background work does not change the last assignment-download counts.
Pulled and Mirrored count processed assignment rows, including updates to records
already on the device. They are not counts of newly created consumers. Settings,
Diagnostics, and the manual sync result also show unique consumer and schedule
counts and repeated rows with the same `(schedule_id, consumer_id)` in that
download. The same consumer assigned to different schedules is valid history.
Mirrored includes updates to existing rows; it does not exclude a row merely
because it was downloaded before. Rows without a real meter number (empty or an
`ACCT-`/`CID-` placeholder) are skipped. The sync summary and audit log report
skipped-row counts and reasons, and manual sync reports problems when any rows
were skipped. Correct the affected meter assignments in the main system before
expecting those records to be available for reading on the device.

A saved reading keeps its read marker for its original schedule when a stale
unread assignment is mirrored, including after successful upload or app restart.
Startup and assignment refresh repair markers previously reset this way using
the saved reading, including offline startup. A new schedule for the same consumer remains unread. Explicit backend
rejection, deletion, or invalidation still reopens the original assignment;
consumer/bill detail refreshes do not rewrite assignment read flags.

Within a grouped route, the device uses `assignment_order` as the authoritative
sequence and never redistributes consumers between readers. Rows without an order
fall back to segment-aware account sorting, so `152-0`, `152-A1`, `152-A2`, and
`152-B1` remain together. Searches match both the complete account number and its
first-three-segment base group. The raw offline assignment cache stores the account
text, order, route ID, and zone-specific schedule ID so the same behavior survives
a device restart.

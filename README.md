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
- While offline, the reader can sign in and browse cached schedules and consumers. A new bill cannot be previewed or
  printed until the backend reserves its shared billing reference. Offline printing requires a future backend feature
  that preallocates non-overlapping reference blocks to devices.
- Offline readings remain in the local SQLite queue and upload automatically or through `Sync Now` when the backend API becomes reachable.
- An invalid or inactive account response from the backend is never bypassed with stale cached credentials.

### Tailscale Funnel

The device uses the same public HTTPS Funnel as the web app:

```text
Device -> https://aspire.tail3de291.ts.net/api -> Node backend:3001 -> PostgreSQL:5432
```

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
It stops on logout or shutdown. A 401 response returns the reader to login;
other heartbeat failures are recorded in sync logs and never block readings.
The backend should show **Active** if a heartbeat arrived within the past
three minutes, **Inactive** after three minutes, and **No registered device**
before the first heartbeat. The device does not send a reader ID in the
heartbeat; the backend must associate it with the authenticated account.
The backend heartbeat endpoint and status display must be deployed separately
from this Raspberry Pi app.

### Billing-reference lifecycle

Before showing a new receipt, the device persists stable reading
and bill UUIDs locally, calls `POST /api/handheld/billing-references/reserve`, and stores the returned
`SLRYYYY######` reference. Timeouts reuse the same UUIDs. The reading-bundle upload sends that exact reference and
separate bill UUID. After the backend confirms the saved bill, the local reservation becomes `Used`; the printed
reference remains permanently assigned to that bill and is never reused. Reprints retain the original reference.

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

The authenticated API supplies billing-policy values for display and diagnostics.
The Node backend owns payment due dates, penalty rates, previous penalties,
current penalties, bill totals, status, and setting IDs. The device sends reading
and base charge data to `/api/handheld/reading-bundles` without those final
fields. `schedule_due_date` is only the reading assignment's End Date.

An offline reading is queued in SQLite as `Pending server calculation`, with no
bill payment due date or penalty. On successful sync, the returned `response.bill`
is saved unchanged in the sync record and its values are mirrored into the local
consumer cache for offline viewing. The returned `billing_policy` is retained for
diagnostics; its values never recalculate a saved bill. When online, the device
refreshes `/api/handheld/consumers/:id/context` before displaying a saved receipt
so overdue penalties and the bill's original `penalty_rate` come from the server.

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

Within a grouped route, the device uses `assignment_order` as the authoritative
sequence and never redistributes consumers between readers. Rows without an order
fall back to segment-aware account sorting, so `152-0`, `152-A1`, `152-A2`, and
`152-B1` remain together. Searches match both the complete account number and its
first-three-segment base group. The raw offline assignment cache stores the account
text, order, route ID, and zone-specific schedule ID so the same behavior survives
a device restart.

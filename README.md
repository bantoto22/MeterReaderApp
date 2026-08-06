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

## Default Login Credentials

| Username | Password | Name        | ID     |
|----------|----------|-------------|--------|
| reader1  | pass123  | Juan Santos | MR-001 |
| reader2  | pass456  | Maria Cruz  | MR-002 |

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
- While offline, the reader can sign in, browse cached schedules and consumers, record readings, and print receipts.
- Offline readings remain in the local SQLite queue and upload automatically or through `Sync Now` when the backend API becomes reachable.
- An invalid or inactive account response from the backend is never bypassed with stale cached credentials.

### Tailscale Funnel

The device uses the same public HTTPS Funnel as the web app:

```text
Device -> https://aspire.tail3de291.ts.net/api -> Node backend:3001 -> PostgreSQL:5432
```

### Handheld UI

- Sync badges are shown in Meter Entry: `Online`, `Offline`, `Pending Sync`, `Sync Failed`.
- Pending count is displayed.
- `Sync Now` triggers manual queue flush.

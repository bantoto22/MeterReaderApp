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
- Online mode: Supabase read/write.
- Offline mode: local SQLite cache + `sync_queue_meter_readings`.
- Reconnect: FIFO queue flush with conflict detection and audit logs.

### Environment

1. Copy `.env.example` to `.env`.
2. Fill in:
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
   - `MAIN_PG_HOST`, `MAIN_PG_PORT`, `MAIN_PG_DB`, `MAIN_PG_USER`, `MAIN_PG_PASSWORD`
3. Enable sync by setting `HANDHELD_SYNC_ENABLED=1`.

If sync is enabled and required env vars are missing, the sync layer raises a clear startup/config error.

### Local Storage

The handheld queue, sync audit log, and consumer cache are stored in the Pi's local SQLite database.
`MAIN_PG_*` is only used as a remote LAN fallback source for consumer pulls when Supabase is unavailable.

### Handheld UI

- Sync badges are shown in Meter Entry: `Online`, `Offline`, `Pending Sync`, `Sync Failed`.
- Pending count is displayed.
- `Sync Now` triggers manual queue flush.

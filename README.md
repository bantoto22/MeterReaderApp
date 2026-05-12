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
python main.py --qt
```

Install dependency first:

```bash
pip install PySide6
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
- Offline mode: local PostgreSQL cache + `sync_queue_meter_readings`.
- Reconnect: FIFO queue flush with conflict detection and audit logs.

### Environment

1. Copy `.env.example` to `.env`.
2. Fill in:
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
   - `LOCAL_PG_HOST`, `LOCAL_PG_PORT`, `LOCAL_PG_DB`, `LOCAL_PG_USER`, `LOCAL_PG_PASSWORD`
   - `MAIN_PG_HOST`, `MAIN_PG_PORT`, `MAIN_PG_DB`, `MAIN_PG_USER`, `MAIN_PG_PASSWORD`
3. Enable sync by setting `HANDHELD_SYNC_ENABLED=1`.

If sync is enabled and required env vars are missing, the sync layer raises a clear startup/config error.

### Migration

Apply `sql/migrations/001_handheld_sync.sql` to local PostgreSQL for queue/cache/audit tables.

### Handheld UI

- Sync badges are shown in Meter Entry: `Online`, `Offline`, `Pending Sync`, `Sync Failed`.
- Pending count is displayed.
- `Sync Now` triggers manual queue flush.

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
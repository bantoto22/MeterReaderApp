# Clear Needs review on the Raspberry Pi

This is a one-time cleanup of the Pi's local Needs review entries. It does not
reset the entire database or change any office reading, bill, or payment.

1. Turn on the Pi and close the Meter Reader app.
2. Copy `src/review_cleanup.py` from this package into the Pi's existing
   `MeterReaderApp/src` folder. Keep the existing database and `.env` file.
3. Open a terminal in the Pi's `MeterReaderApp` folder and run:

   ```sh
   python3 src/review_cleanup.py --apply
   ```

4. Check that the output shows `"needs_review": 0`. The output also lists the
   number removed and the backup path in `data/backups`.
5. Reopen the app and tap **Settings -> Sync Now** to retrieve current office
   assignments and meter baselines. Check that **Needs review** is zero.

The command first verifies a full SQLite backup. It removes only queue entries
whose backend status is `needs_review`. Their unconfirmed local readings are
marked deleted, so they no longer count as completed work or supply a meter
baseline. Matching unissued draft bills are removed from the local bill cache.
Other queued uploads, confirmed readings, and printed receipt history are kept.
Allocated billing references are retained; unused references belonging to cleared
entries become `Discarded` and cannot be reused for a new reading.

To preview without changing the database, omit `--apply`:

```sh
python3 src/review_cleanup.py
```

If the app uses a different database path, specify it with `--db /path/to/meter.db`.
This command never creates a missing database. Run it with the app closed so the
queue cannot change during cleanup. Backups contain the original records.

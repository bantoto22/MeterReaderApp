# Device check before the defense

The local Windows test suite passes 218 tests. Raspberry Pi startup, backend
connectivity, and physical USB printing still need to be checked on the device.
Use designated demo consumers and their assigned schedules for these steps.

1. **Deploy and start.** Close the Pi app and back up its `data` directory. Copy
   the updated `src` and `assets/qml` directories together, preserving the Pi's
   `.env` and existing `data`. Restart using the usual launcher. Confirm login
   and route screens open without errors.
2. **Prepare online.** Sign in online and tap **Sync Now**. Confirm the assignment
   download succeeded with fresh backend data and reference preparation has no
   failures. Check the demo consumers' opening readings and coverage in the main
   system before disconnecting. A successful health check alone does not verify
   an authenticated assignment download.
3. **Print online.** On the first demo consumer, enter its previous reading plus
   3 (for example, previous `100`, present `103`). Expect `3 m3` consumption.
   Save and print. Check the exact `SLRYYYY######` reference, consumer, meter,
   coverage start and end, payment due date, and total against the saved bill.
   Coverage follows the assigned billing period; Reading Date is the capture
   date and can differ from the coverage end for a late reading.
4. **Save and print offline.** Turn Wi-Fi off. On a second prepared demo
   consumer, enter its previous reading plus 3 and save. Expect the reading to
   remain available locally and its upload to be queued. With a cached reference
   and valid coverage, expect a physical receipt. Record its reference and dates.
5. **Restart offline and reprint.** Close and reopen the app without Wi-Fi.
   Confirm cached login/routes and the saved reading remain accessible. Reprint
   the second receipt. Its reference and coverage must match the original.
6. **Reconnect and reconcile.** Restore Wi-Fi and tap **Sync Now**. Confirm the
   queued demo reading uploads, the backend keeps the same reference and coverage,
   and there is one bill for that reading. Reprint again and compare the reference
   and coverage with the original offline receipt.

If printing is held for coverage review, retain the saved reading and reference.
Have the Billing Officer investigate and correct the opening reading or bill
coverage in the main system, then sync and retry the existing bill's reprint.
Sync alone does not repair an incorrect backend bill. Keep the database and
reference reservations intact while investigating.

Missing, malformed, impossible, and reversed coverage dates are tested locally
with a mocked printer. Do not corrupt live data to repeat those fault tests on
the device.

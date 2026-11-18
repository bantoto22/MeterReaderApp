# Recover a saved first reading after verifying its zero baseline

A missing previous reading is different from a verified previous reading of zero.
If the backend reports that the account's connection date and meter history need
review, the saved device entry remains available for review until the office
confirms a valid starting point. Newly registered connections with the required
registration records still receive zero automatically.

For a confirmed zero starting reading that the office has not recorded yet:

1. In the main system, sign in as an Admin or Billing Officer and open
   **Generate Bills**. Select the consumer in the manual bill form and the
   relevant reading schedule.
2. In **Opening meter reading**, enter the verified opening date and **0** as
   the opening value. Confirm verification and click **Save opening reading**.
   This records the starting point; the existing device entry supplies the
   actual present reading and its already reserved reference.
3. With the Pi app closed, extract this update into its existing MeterReaderApp
   folder. Reopen the app, sign in as the original reader, and tap
   **Settings -> Sync Now**.
4. Check that the saved entry uploads with previous reading **0**, the original
   present reading, and the original billing reference. Check the resulting
   reading and bill in the main system. Repeat sync must not create a second bill.

Sync rechecks the office baseline, consumer, original reader, meter, coverage
date, and existing billing-cycle reading. Only a missing initial value associated
with the specific account-setup error can be recovered. Existing nonzero baselines,
unrelated conflicts, restored review-history entries, and confirmed duplicates are
not converted to zero. The original and recovered payloads are recorded in the
local sync audit. The backend validates the upload again before accepting it.

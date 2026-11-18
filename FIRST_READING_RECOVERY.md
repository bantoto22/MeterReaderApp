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
3. With the Pi app closed, update its existing MeterReaderApp Git checkout after
   the source changes have been committed and pushed. Preserve the local database.
   Reopen the app, sign in as the original reader, and tap
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

If the office already saved the full first bill using **Save Bill**, keep that
office bill. Update the Pi's Git checkout with the current source changes,
restart the app, sign in as the original reader, and run **Settings -> Sync Now**.
The old missing-opening-reading hold can now be checked against the existing
office reading and active bill. The account and billing cycle must match, the
office previous value must be zero, and the present reading and consumption must
match the device capture. The original meter is also checked. A successful
check moves the extra device entry into **Settings -> Review history -> History**
and reports **Duplicates ignored**. It does not upload a second reading or issue
another bill. History keeps the original unknown previous value, captured values,
IDs and reserved reference, alongside the verified office reading ID and reference.
Missing office records, changed values, a different meter or reader, and restored
history entries remain in review. Repeat sync leaves archived entries in History.

## Update through Git

The fix is in the normal source files. Commit and push those changes before
updating the Pi from GitHub. Close the Pi app before updating its checkout and
preserve `data/meter.db`, including any local changes reported by Git. Reopen
the app after updating, sign in as the original reader, and tap
**Settings -> Sync Now**. A confirmed duplicate leaves Needs review and appears
in **Review history -> History**, with its office reading ID and bill reference
available for comparison. Other unresolved entries remain in review.

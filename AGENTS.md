# Device operating requirements

- The device normally runs offline. Connectivity is used to synchronize data
  with the main system and report presence while connected.
- After initial account and route provisioning, cached login, cached route
  access, and recording readings must work using local SQLite without internet.
- Save readings locally and retain queued operations across disconnections,
  backend failures, and online session expiry.
- Online authentication and heartbeats must not be requirements for continuing
  local field work. Expiring an online session must not log the reader out of
  the local app or discard an unfinished reading.
- Require valid backend authentication for synchronization. An explicit account
  or credential rejection must not be bypassed for online operations.
- Prepare assigned route data and backend-issued billing references during sync
  so scheduled offline bills can use cached references. Preserve the shared
  backend billing-reference allocation rules.
- The main system can report live presence only while connected. A stale
  heartbeat does not prove that an offline device has stopped working.

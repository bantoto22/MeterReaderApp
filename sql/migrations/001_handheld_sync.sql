-- Handheld offline/online sync tables (local PostgreSQL)
-- Schema target: water_billing (uses current search_path if already set)

CREATE TABLE IF NOT EXISTS sync_queue_meter_readings (
    id BIGSERIAL PRIMARY KEY,
    operation VARCHAR(20) NOT NULL,
    operation_id UUID NOT NULL UNIQUE,
    reading_id UUID NOT NULL,
    consumer_id BIGINT NOT NULL,
    reading_date DATE NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    retries INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    conflict_reason TEXT,
    server_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    synced_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sync_queue_status_created_at
  ON sync_queue_meter_readings (status, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sync_queue_stable_key
  ON sync_queue_meter_readings (consumer_id, reading_date, operation_id);

CREATE TABLE IF NOT EXISTS sync_audit_log (
    id BIGSERIAL PRIMARY KEY,
    queue_id BIGINT,
    status VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS handheld_consumers_cache (
    id BIGINT PRIMARY KEY,
    meter_no TEXT,
    acct_no TEXT,
    name TEXT NOT NULL,
    zone_name TEXT,
    previous_reading INTEGER,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

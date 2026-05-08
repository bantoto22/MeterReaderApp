"""
Handheld sync layer for online/offline meter reading operations.

Online:
- Reads/writes via Supabase REST.

Offline:
- Writes are queued in local PostgreSQL.
- Reads use local cached consumers/meters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import threading
import time
import uuid
from urllib import error, parse, request

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SyncConfig:
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    local_pg_host: str
    local_pg_port: int
    local_pg_db: str
    local_pg_user: str
    local_pg_password: str
    main_pg_host: str
    main_pg_port: int
    main_pg_db: str
    main_pg_user: str
    main_pg_password: str
    sync_enabled: bool = False

    @classmethod
    def from_env(cls, fail_fast: bool = False) -> "SyncConfig":
        load_dotenv()

        sync_enabled = os.getenv("HANDHELD_SYNC_ENABLED", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}
        required = [
            "SUPABASE_URL",
            "SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "LOCAL_PG_HOST",
            "LOCAL_PG_PORT",
            "LOCAL_PG_DB",
            "LOCAL_PG_USER",
            "LOCAL_PG_PASSWORD",
            "MAIN_PG_HOST",
            "MAIN_PG_PORT",
            "MAIN_PG_DB",
            "MAIN_PG_USER",
            "MAIN_PG_PASSWORD",
        ]

        missing = [k for k in required if not os.getenv(k)]
        if (fail_fast or sync_enabled) and missing:
            raise RuntimeError(
                "Missing required sync environment variables: "
                + ", ".join(missing)
                + ". Update .env from .env.example."
            )

        return cls(
            supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
            supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
            local_pg_host=os.getenv("LOCAL_PG_HOST", ""),
            local_pg_port=int(os.getenv("LOCAL_PG_PORT", "5432")),
            local_pg_db=os.getenv("LOCAL_PG_DB", ""),
            local_pg_user=os.getenv("LOCAL_PG_USER", ""),
            local_pg_password=os.getenv("LOCAL_PG_PASSWORD", ""),
            main_pg_host=os.getenv("MAIN_PG_HOST", ""),
            main_pg_port=int(os.getenv("MAIN_PG_PORT", "5432")),
            main_pg_db=os.getenv("MAIN_PG_DB", ""),
            main_pg_user=os.getenv("MAIN_PG_USER", ""),
            main_pg_password=os.getenv("MAIN_PG_PASSWORD", ""),
            sync_enabled=sync_enabled,
        )


class LocalSyncStore:
    def ensure_schema(self) -> None:
        raise NotImplementedError

    def cache_consumers(self, consumers: list[dict]) -> None:
        raise NotImplementedError

    def load_cached_consumers(self, zone_name: str | None = None) -> list[dict]:
        raise NotImplementedError

    def enqueue_operation(self, operation: str, payload: dict) -> dict:
        raise NotImplementedError

    def list_pending(self) -> list[dict]:
        raise NotImplementedError

    def mark_synced(self, queue_id: int) -> None:
        raise NotImplementedError

    def mark_failed(self, queue_id: int, reason: str) -> None:
        raise NotImplementedError

    def mark_conflict(self, queue_id: int, reason: str, server_payload: dict | None = None) -> None:
        raise NotImplementedError

    def log_audit(self, queue_id: int | None, status: str, message: str, payload: dict | None = None) -> None:
        raise NotImplementedError


class PostgresLocalSyncStore(LocalSyncStore):
    def __init__(self, cfg: SyncConfig):
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2 is required for local PostgreSQL sync storage. Install it with `pip install psycopg2-binary`."
            ) from exc
        self._psycopg2 = psycopg2
        self._dict_cursor = RealDictCursor
        self._cfg = cfg

    def _connect(self):
        return self._psycopg2.connect(
            host=self._cfg.local_pg_host,
            port=self._cfg.local_pg_port,
            dbname=self._cfg.local_pg_db,
            user=self._cfg.local_pg_user,
            password=self._cfg.local_pg_password,
        )

    def ensure_schema(self) -> None:
        sql = """
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
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()

    def cache_consumers(self, consumers: list[dict]) -> None:
        if not consumers:
            return
        sql = """
        INSERT INTO handheld_consumers_cache (id, meter_no, acct_no, name, zone_name, previous_reading, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (id) DO UPDATE SET
            meter_no = EXCLUDED.meter_no,
            acct_no = EXCLUDED.acct_no,
            name = EXCLUDED.name,
            zone_name = EXCLUDED.zone_name,
            previous_reading = EXCLUDED.previous_reading,
            updated_at = NOW()
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                for item in consumers:
                    cur.execute(
                        sql,
                        (
                            item.get("id"),
                            item.get("meter_no"),
                            item.get("acct_no"),
                            item.get("name", ""),
                            item.get("zone_name"),
                            item.get("previous_reading"),
                        ),
                    )
            conn.commit()

    def load_cached_consumers(self, zone_name: str | None = None) -> list[dict]:
        base = """
        SELECT id, meter_no, acct_no, name, zone_name, previous_reading
        FROM handheld_consumers_cache
        """
        params: tuple = ()
        if zone_name:
            base += " WHERE zone_name = %s"
            params = (zone_name,)
        base += " ORDER BY meter_no"
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._dict_cursor) as cur:
                cur.execute(base, params)
                rows = cur.fetchall()
        return list(rows)

    def enqueue_operation(self, operation: str, payload: dict) -> dict:
        operation_id = payload.get("operation_id") or str(uuid.uuid4())
        reading_id = payload.get("reading_id") or str(uuid.uuid4())
        payload["operation_id"] = operation_id
        payload["reading_id"] = reading_id
        sql = """
        INSERT INTO sync_queue_meter_readings (
            operation, operation_id, reading_id, consumer_id, reading_date, payload, status
        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'pending')
        RETURNING id, operation_id, reading_id, status, created_at
        """
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._dict_cursor) as cur:
                cur.execute(
                    sql,
                    (
                        operation,
                        operation_id,
                        reading_id,
                        payload["consumer_id"],
                        payload["reading_date"],
                        json.dumps(payload),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return dict(row)

    def list_pending(self) -> list[dict]:
        sql = """
        SELECT id, operation, operation_id, reading_id, consumer_id, reading_date, payload, status, retries, last_error, created_at
        FROM sync_queue_meter_readings
        WHERE status IN ('pending', 'failed')
        ORDER BY id ASC
        """
        with self._connect() as conn:
            with conn.cursor(cursor_factory=self._dict_cursor) as cur:
                cur.execute(sql)
                rows = cur.fetchall()
        return list(rows)

    def mark_synced(self, queue_id: int) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sync_queue_meter_readings
                    SET status='synced', synced_at=NOW(), updated_at=NOW(), last_error=NULL
                    WHERE id = %s
                    """,
                    (queue_id,),
                )
            conn.commit()

    def mark_failed(self, queue_id: int, reason: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sync_queue_meter_readings
                    SET status='failed', retries=retries+1, last_error=%s, updated_at=NOW()
                    WHERE id=%s
                    """,
                    (reason[:1000], queue_id),
                )
            conn.commit()

    def mark_conflict(self, queue_id: int, reason: str, server_payload: dict | None = None) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sync_queue_meter_readings
                    SET status='conflict', conflict_reason=%s, server_payload=%s::jsonb, updated_at=NOW()
                    WHERE id=%s
                    """,
                    (reason[:1000], json.dumps(server_payload or {}), queue_id),
                )
            conn.commit()

    def log_audit(self, queue_id: int | None, status: str, message: str, payload: dict | None = None) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sync_audit_log(queue_id, status, message, payload)
                    VALUES (%s, %s, %s, %s::jsonb)
                    """,
                    (queue_id, status, message[:2000], json.dumps(payload or {})),
                )
            conn.commit()


class SupabaseRestClient:
    def __init__(self, cfg: SyncConfig):
        self._url = cfg.supabase_url
        self._anon_key = cfg.supabase_anon_key
        self._service_key = cfg.supabase_service_role_key

    def _req(self, method: str, table_or_path: str, *, query: dict | None = None, payload: dict | list | None = None,
             use_service_key: bool = False, extra_headers: dict | None = None) -> tuple[int, object]:
        base = table_or_path if table_or_path.startswith("/") else f"/rest/v1/{table_or_path}"
        url = f"{self._url}{base}"
        if query:
            url += "?" + parse.urlencode(query)
        body = None
        headers = {
            "apikey": self._service_key if use_service_key else self._anon_key,
            "Authorization": f"Bearer {self._service_key if use_service_key else self._anon_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=body, method=method, headers=headers)
        try:
            with request.urlopen(req, timeout=6) as resp:
                raw = resp.read().decode("utf-8").strip()
                return resp.getcode(), json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8").strip() if exc.fp else ""
            try:
                return exc.code, json.loads(raw) if raw else {"error": raw or str(exc)}
            except Exception:
                return exc.code, {"error": raw or str(exc)}
        except Exception as exc:
            return 0, {"error": str(exc)}

    def is_online(self) -> bool:
        status, _ = self._req("GET", "/rest/v1/", use_service_key=False)
        return 200 <= status < 500 and status != 0

    def load_assigned_consumers(self, zone_name: str | None = None) -> list[dict]:
        query = {"select": "id,meter_no,acct_no,name,previous_reading,zone_name"}
        if zone_name:
            query["zone_name"] = f"eq.{zone_name}"
        status, data = self._req("GET", "consumer", query=query, use_service_key=False)
        if status >= 400:
            raise RuntimeError(f"Supabase read failed: {data}")
        return data if isinstance(data, list) else []

    def find_existing_reading(self, consumer_id: int, reading_date: str) -> dict | None:
        query = {
            "select": "reading_id,consumer_id,reading_date,updated_at,present_reading",
            "consumer_id": f"eq.{consumer_id}",
            "reading_date": f"eq.{reading_date}",
            "order": "updated_at.desc",
            "limit": "1",
        }
        status, data = self._req("GET", "meterreadings", query=query, use_service_key=True)
        if status >= 400:
            return None
        if isinstance(data, list) and data:
            return data[0]
        return None

    def upsert_meter_reading(self, payload: dict) -> dict:
        headers = {
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        status, data = self._req(
            "POST",
            "meterreadings",
            payload=payload,
            use_service_key=True,
            extra_headers=headers,
            query={"on_conflict": "reading_id"},
        )
        if status >= 400:
            raise RuntimeError(f"Supabase write failed: {data}")
        if isinstance(data, list) and data:
            return data[0]
        return payload


class HandheldSyncDataAccess:
    """
    Required handheld DAL methods:
    - loadAssignedConsumers
    - saveMeterReading
    - updateMeterReading
    - listPendingSyncReadings
    - syncPendingReadings
    """

    def __init__(self, local_store: LocalSyncStore, remote_store: SupabaseRestClient):
        self.local = local_store
        self.remote = remote_store
        self._worker_stop = threading.Event()
        self._worker: threading.Thread | None = None
        self.local.ensure_schema()

    @classmethod
    def from_env(cls, fail_fast: bool = False) -> "HandheldSyncDataAccess":
        cfg = SyncConfig.from_env(fail_fast=fail_fast)
        return cls(PostgresLocalSyncStore(cfg), SupabaseRestClient(cfg))

    def is_online(self) -> bool:
        return self.remote.is_online()

    def loadAssignedConsumers(self, zone_name: str | None = None) -> list[dict]:
        if self.is_online():
            try:
                data = self.remote.load_assigned_consumers(zone_name)
                self.local.cache_consumers(data)
                self.local.log_audit(None, "success", "Loaded assigned consumers from Supabase", {"count": len(data)})
                return data
            except Exception as exc:
                self.local.log_audit(None, "failed", f"Supabase load failed, fallback to cache: {exc}")
        cached = self.local.load_cached_consumers(zone_name)
        self.local.log_audit(None, "success", "Loaded assigned consumers from local cache", {"count": len(cached)})
        return cached

    def _normalize_reading(self, payload: dict) -> dict:
        reading = dict(payload)
        reading.setdefault("reading_id", str(uuid.uuid4()))
        reading.setdefault("operation_id", str(uuid.uuid4()))
        reading.setdefault("created_at", _utc_now_iso())
        reading.setdefault("updated_at", _utc_now_iso())
        if "reading_date" not in reading:
            reading["reading_date"] = datetime.now(timezone.utc).date().isoformat()
        return reading

    def saveMeterReading(self, payload: dict) -> dict:
        reading = self._normalize_reading(payload)
        if self.is_online():
            try:
                remote_result = self.remote.upsert_meter_reading(reading)
                self.local.log_audit(None, "success", "Online save to Supabase", {"reading_id": reading["reading_id"]})
                return {"status": "synced", "remote": remote_result, "reading": reading}
            except Exception as exc:
                self.local.log_audit(None, "failed", f"Online save failed, queued offline: {exc}", reading)
        queued = self.local.enqueue_operation("create", reading)
        self.local.log_audit(queued["id"], "pending", "Queued offline create operation", reading)
        return {"status": "queued", "queue": queued, "reading": reading}

    def updateMeterReading(self, payload: dict) -> dict:
        reading = self._normalize_reading(payload)
        if self.is_online():
            try:
                remote_result = self.remote.upsert_meter_reading(reading)
                self.local.log_audit(None, "success", "Online update to Supabase", {"reading_id": reading["reading_id"]})
                return {"status": "synced", "remote": remote_result, "reading": reading}
            except Exception as exc:
                self.local.log_audit(None, "failed", f"Online update failed, queued offline: {exc}", reading)
        queued = self.local.enqueue_operation("update", reading)
        self.local.log_audit(queued["id"], "pending", "Queued offline update operation", reading)
        return {"status": "queued", "queue": queued, "reading": reading}

    def listPendingSyncReadings(self) -> list[dict]:
        return self.local.list_pending()

    def syncPendingReadings(self) -> dict:
        if not self.is_online():
            self.local.log_audit(None, "failed", "Sync skipped, offline")
            return {"status": "offline", "synced": 0, "failed": 0, "conflicts": 0}

        pending = self.local.list_pending()
        synced = 0
        failed = 0
        conflicts = 0

        for row in pending:
            queue_id = row["id"]
            payload = row["payload"]
            try:
                existing = self.remote.find_existing_reading(payload["consumer_id"], payload["reading_date"])
                if existing and existing.get("updated_at") and payload.get("updated_at"):
                    if str(existing["updated_at"]) > str(payload["updated_at"]):
                        reason = "Server has newer reading for same consumer/date."
                        self.local.mark_conflict(queue_id, reason, existing)
                        self.local.log_audit(queue_id, "conflict", reason, {"local": payload, "server": existing})
                        conflicts += 1
                        continue

                self.remote.upsert_meter_reading(payload)
                self.local.mark_synced(queue_id)
                self.local.log_audit(queue_id, "success", "Queue row synced", payload)
                synced += 1
            except Exception as exc:
                self.local.mark_failed(queue_id, str(exc))
                self.local.log_audit(queue_id, "failed", f"Queue row sync failed: {exc}", payload)
                failed += 1

        return {"status": "done", "synced": synced, "failed": failed, "conflicts": conflicts}

    def start_sync_worker(self, interval_seconds: int = 15) -> None:
        if self._worker and self._worker.is_alive():
            return

        self._worker_stop.clear()

        def _run():
            while not self._worker_stop.is_set():
                try:
                    self.syncPendingReadings()
                except Exception as exc:
                    self.local.log_audit(None, "failed", f"Background sync worker error: {exc}")
                time.sleep(max(3, interval_seconds))

        self._worker = threading.Thread(target=_run, daemon=True, name="handheld-sync-worker")
        self._worker.start()

    def stop_sync_worker(self) -> None:
        self._worker_stop.set()

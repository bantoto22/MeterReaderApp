"""Shared SQLite connection helpers for responsive concurrent device access."""

from __future__ import annotations

import sqlite3
import threading
import time


_EXECUTE_LOCK = threading.RLock()
_LOCK_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.0)


def _is_lock_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def _retry_locked(operation):
    for delay in (*_LOCK_RETRY_DELAYS, None):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if not _is_lock_error(exc) or delay is None:
                raise
            time.sleep(delay)


class RetryingCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        return self.connection._run_statement(
            sql,
            lambda: super(RetryingCursor, self).execute(sql, parameters),
        )

    def executemany(self, sql, seq_of_parameters):
        return self.connection._run_statement(
            sql,
            lambda: super(RetryingCursor, self).executemany(sql, seq_of_parameters),
        )

    def executescript(self, sql_script):
        return self.connection._run_statement(
            sql_script,
            lambda: super(RetryingCursor, self).executescript(sql_script),
        )


class RetryingConnection(sqlite3.Connection):
    _owns_write_lock = False

    @staticmethod
    def _is_write_statement(sql: str) -> bool:
        first_token = str(sql or "").lstrip().split(None, 1)[0].upper() if str(sql or "").strip() else ""
        return first_token not in {"SELECT", "EXPLAIN"}

    def _release_write_lock(self) -> None:
        if self._owns_write_lock:
            self._owns_write_lock = False
            _EXECUTE_LOCK.release()

    def _run_statement(self, sql: str, operation):
        acquired_here = False
        if self._is_write_statement(sql) and not self._owns_write_lock:
            _EXECUTE_LOCK.acquire()
            self._owns_write_lock = True
            acquired_here = True
        try:
            result = _retry_locked(operation)
        except Exception:
            if acquired_here and not self.in_transaction:
                self._release_write_lock()
            raise
        if acquired_here and not self.in_transaction:
            self._release_write_lock()
        return result

    def cursor(self, factory=RetryingCursor):
        return super().cursor(factory)

    def execute(self, sql, parameters=()):
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters):
        return self.cursor().executemany(sql, seq_of_parameters)

    def executescript(self, sql_script):
        return self.cursor().executescript(sql_script)

    def commit(self):
        try:
            return _retry_locked(lambda: super(RetryingConnection, self).commit())
        finally:
            if not self.in_transaction:
                self._release_write_lock()

    def rollback(self):
        try:
            return super().rollback()
        finally:
            self._release_write_lock()

    def close(self):
        try:
            return super().close()
        finally:
            self._release_write_lock()


def connect_sqlite(path: str) -> RetryingConnection:
    """Open a connection that retries brief writer contention without a 15-second UI stall."""
    connection = sqlite3.connect(path, timeout=0.25, factory=RetryingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 250")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

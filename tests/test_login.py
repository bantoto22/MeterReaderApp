import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.handheld_sync import BackendApiClient, SyncConfig
from src.qt_hybrid_app import LoginBridge


class LoginTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db_patch = patch.object(database, "_db_path", return_value=str(Path(directory.name) / "meter.db"))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database.init_db()
        self.user = {
            "id": 12, "account_id": 12, "username": "field.reader",
            "full_name": "Field Reader Test", "role_id": 3, "account_status": "Active",
        }
        database.cache_meter_reader_credentials(self.user, "cached-secret")
        self.client = BackendApiClient(SyncConfig(backend_api_base_url="https://example.test/api"))
        self.bridge = LoginBridge()
        self.bridge._sync_dal = SimpleNamespace(authenticateMeterReader=self.client.authenticate_meter_reader)
        self.successes = []
        self.failures = []
        self.bridge.loginSuccess.connect(self.successes.append)
        self.bridge.loginFailed.connect(lambda: self.failures.append(self.bridge.errorMessage))

    def attempt(self, status, data, username="field.reader", password="cached-secret"):
        # Run the worker inline so signal delivery is deterministic without a GUI.
        with patch.object(self.client, "_req", return_value=(status, data)), patch(
            "src.qt_hybrid_app.threading.Thread",
            side_effect=lambda *, target, daemon: SimpleNamespace(start=target),
        ):
            self.bridge.attemptLogin(username, password)
        self.assertFalse(self.bridge.loginBusy)

    def test_unavailable_backend_allows_cached_login(self):
        for status in (0, 404, 408, 429, 500, 502, 503):
            with self.subTest(status=status):
                self.successes.clear()
                self.attempt(status, {"error": "Backend unavailable"})
                self.assertEqual(len(self.successes), 1)
                self.assertEqual(self.successes[0]["account_id"], 12)
                self.assertEqual(self.failures, [])

    def test_explicit_rejection_never_uses_cached_credentials(self):
        for status in (200, 400, 401, 403):
            with self.subTest(status=status):
                self.failures.clear()
                self.attempt(status, {"success": False, "message": "Account access denied"})
                self.assertEqual(self.successes, [])
                self.assertEqual(self.failures, ["Account access denied"])

    def test_uncached_account_gets_connection_error_and_first_login_guidance(self):
        self.attempt(503, {"error": "Service unavailable"}, username="uncached.reader")
        self.assertEqual(self.successes, [])
        self.assertIn("HTTP 503 /api/login", self.failures[0])
        self.assertIn("Connect once with this account", self.failures[0])

    def test_wrong_cached_password_cannot_login_offline(self):
        self.attempt(0, {"error": "Connection refused"}, password="wrong-secret")
        self.assertEqual(self.successes, [])
        self.assertIn("Connection error /api/login", self.failures[0])

    def test_online_login_caches_credentials_for_later_offline_login(self):
        self.attempt(200, {"success": True, "user": self.user}, password="new-secret")
        self.assertEqual(len(self.successes), 1)
        self.assertIsNotNone(database.authenticate_user("field.reader", "new-secret"))
        self.successes.clear()
        self.attempt(0, {"error": "Connection refused"}, password="new-secret")
        self.assertEqual(len(self.successes), 1)


if __name__ == "__main__":
    unittest.main()

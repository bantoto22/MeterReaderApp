import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
        self.attempt(200, {"success": True, "token": "device-session", "user": self.user}, password="new-secret")
        self.assertEqual(len(self.successes), 1)
        self.assertIsNotNone(database.authenticate_user("field.reader", "new-secret"))
        self.successes.clear()
        self.attempt(0, {"error": "Connection refused"}, password="new-secret")
        self.assertEqual(len(self.successes), 1)

    def test_tokenless_login_reports_backend_protocol_problem_for_uncached_reader(self):
        user = {**self.user, "username": "uncached.reader"}
        self.attempt(200, {"success": True, "csrfToken": "browser-csrf", "user": user}, username=user["username"])
        self.assertEqual(self.successes, [])
        self.assertIn("did not return a device session token", self.failures[0])
        self.assertEqual(self.client._session_token, "")
        self.assertIsNone(self.client._meter_reader_id)

    def test_login_identifies_native_client_and_clears_previous_session(self):
        self.client.set_authenticated_session("previous-session", 99)
        response = Mock()
        response.getcode.return_value = 200
        response.read.return_value = b'{"success":true,"token":"device-session","user":{"id":12,"username":"field.reader","role_id":3}}'
        with patch("src.handheld_sync.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = response
            user = self.client.authenticate_meter_reader("field.reader", "cached-secret")
        req = urlopen.call_args.args[0]
        self.assertEqual(req.get_header("X-slr-client"), "handheld")
        self.assertIsNone(req.get_header("Authorization"))
        self.assertIsNone(req.get_header("Cookie"))
        self.assertIsNone(req.get_header("Origin"))
        self.assertEqual(user["session_token"], "device-session")


if __name__ == "__main__":
    unittest.main()

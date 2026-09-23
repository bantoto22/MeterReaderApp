import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.handheld_sync import APP_VERSION, BackendApiClient, SyncConfig
from src.qt_hybrid_app import AppBridge, HybridMainWindow, run_qt_hybrid


class FakeSignal:
    def __init__(self, callback=None):
        self.callback = callback
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)
        if self.callback:
            self.callback(*args)

    def connect(self, callback):
        self.callback = callback


class FakeTimer:
    def __init__(self):
        self.active = False
        self.started = 0

    def start(self):
        self.active = True
        self.started += 1

    def stop(self):
        self.active = False


class FakeThread:
    def __init__(self, *, target, daemon, name):
        self.target = target
        self.alive = False

    def start(self):
        self.alive = True

    def finish(self):
        self.target()
        self.alive = False

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.alive = False


class FakeDal:
    def __init__(self):
        self.remote = SimpleNamespace(_session_token="")
        self.responses = [(200, {"success": True})]
        self.sent = 0
        self.audit = []
        self.sessions = []

    def setAuthenticatedSession(self, token, reader_id):
        self.remote._session_token = token or ""
        self.sessions.append((token, reader_id))

    def sendDeviceHeartbeat(self):
        self.sent += 1
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def _audit(self, queue_id, status, message):
        self.audit.append((status, message))

    def saveMeterReading(self, payload):
        return {"status": "queued", "reading": payload}


class DeviceHeartbeatTests(unittest.TestCase):
    def test_application_timer_is_set_to_sixty_seconds(self):
        class ConstructorTimer(FakeTimer):
            def __init__(self, parent=None):
                super().__init__()
                self.timeout = FakeSignal()
                self.interval = None

            def setInterval(self, milliseconds):
                self.interval = milliseconds

        with patch("src.qt_hybrid_app.QTimer", ConstructorTimer), patch(
            "src.qt_hybrid_app.get_latest_receipt_print", return_value=None
        ), patch.object(AppBridge, "_load_auto_sync_enabled", return_value=False), patch.object(
            AppBridge, "_init_sync"
        ), patch.object(AppBridge, "refreshWifiStatus"), patch.object(
            AppBridge, "refreshWifiNetworks"
        ), patch.object(AppBridge, "refreshPrintHistory"), patch.object(
            AppBridge, "update_stats"
        ), patch.object(AppBridge, "_refresh_search_suggestions"), patch.object(
            AppBridge, "_refresh_zone_consumers"
        ):
            bridge = AppBridge()
        self.assertEqual(bridge._heartbeat_timer.interval, 60_000)

    def _view(self):
        dal = FakeDal()
        view = SimpleNamespace(
            _sync_dal=dal, _heartbeat_dal=None, _heartbeat_timer=FakeTimer(),
            _heartbeat_generation=0, _heartbeat_in_flight=False,
            _heartbeat_thread=None, _heartbeat_authenticated=False,
            _heartbeat_config_invalid=False,
            _heartbeat_retry_count=0, _heartbeat_next_allowed=0.0,
            _wifi_status="Status: Disconnected", _wifi_status_color="",
            _reader_name="", _reader_id="", _meter_reader_account_id="",
            _route_selected_by_user=False,
            _refresh_local_assignment_views=lambda: None,
            _start_assigned_consumer_dataset_refresh=lambda: None,
            _start_reconnect_sync=lambda: None,
        )
        for name in (
            "readerNameChanged", "readerIdChanged", "canReprintChanged",
            "wifiStatusChanged", "wifiStatusColorChanged", "zonesChanged",
            "selectedZoneChanged", "zoneConsumersChanged", "searchSuggestionsChanged",
            "searchQueryChanged",
        ):
            setattr(view, name, FakeSignal())
        view.heartbeatResult = FakeSignal(lambda *args: AppBridge._finish_heartbeat(view, *args))
        view.sessionExpired = FakeSignal()
        view._start_heartbeat = lambda: AppBridge._start_heartbeat(view)
        view.stop_heartbeat = lambda: AppBridge.stop_heartbeat(view)
        return view, dal

    def _login(self, view):
        with patch("src.qt_hybrid_app.get_latest_receipt_print", return_value=None), patch(
            "src.qt_hybrid_app.QTimer.singleShot"
        ):
            AppBridge.set_user(view, {"account_id": 12, "username": "reader", "session_token": "session-secret"})

    def test_missing_id_fails_before_gui_startup(self):
        with patch("src.qt_hybrid_app.SyncConfig.from_env", side_effect=RuntimeError("Device ID missing")), patch(
            "src.qt_hybrid_app.init_db"
        ) as init_db:
            with self.assertRaisesRegex(RuntimeError, "Device ID missing"):
                run_qt_hybrid()
            init_db.assert_not_called()

    def test_config_is_stable_required_and_bounded(self):
        values = {
            "BACKEND_API_BASE_URL": "https://example.test/api",
            "HANDHELD_DEVICE_ID": "SLR-RPI-001",
            "SLR_DEVICE_LABEL": "Reader Unit 01",
        }
        with patch.dict(os.environ, values, clear=True), patch("src.handheld_sync.load_dotenv", return_value=True):
            self.assertEqual(SyncConfig.from_env(fail_fast=True).device_id, "SLR-RPI-001")
            self.assertEqual(SyncConfig.from_env(fail_fast=True).device_id, "SLR-RPI-001")
            self.assertEqual(SyncConfig.from_env().device_label, "Reader Unit 01")
            os.environ.pop("HANDHELD_DEVICE_ID")
            with self.assertRaisesRegex(RuntimeError, "permanent HANDHELD_DEVICE_ID"):
                SyncConfig.from_env(fail_fast=True)
            os.environ["SLR_DEVICE_ID"] = "SLR-RPI-002"
            self.assertEqual(SyncConfig.from_env(fail_fast=True).device_id, "SLR-RPI-002")
            os.environ["HANDHELD_DEVICE_ID"] = "SLR-RPI-001"
            with self.assertRaisesRegex(RuntimeError, "must match"):
                SyncConfig.from_env(fail_fast=True)
            os.environ.pop("SLR_DEVICE_ID")
            os.environ["HANDHELD_DEVICE_ID"] = "x" * 121
            with self.assertRaisesRegex(RuntimeError, "at most 120"):
                SyncConfig.from_env(fail_fast=True)
            os.environ["HANDHELD_DEVICE_ID"] = "SLR-RPI-001"
            os.environ["SLR_DEVICE_LABEL"] = "x" * 201
            with self.assertRaisesRegex(RuntimeError, "at most 200"):
                SyncConfig.from_env(fail_fast=True)
            os.environ["SLR_DEVICE_LABEL"] = "Reader Unit 01"
            os.environ["BACKEND_API_BASE_URL"] = "http://example.test/api"
            with self.assertRaisesRegex(RuntimeError, "must use HTTPS"):
                SyncConfig.from_env(fail_fast=True)

    def test_client_uses_existing_bearer_auth_url_and_ten_second_timeout(self):
        client = BackendApiClient(SyncConfig(
            backend_api_base_url="https://example.test/api",
            device_id="SLR-RPI-001", device_label="Reader Unit 01",
        ))
        client.set_authenticated_session("session-secret", 12)

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"success":true}'

            def getcode(self):
                return 200

        with patch("src.handheld_sync.request.urlopen", return_value=Response()) as urlopen:
            self.assertEqual(client.send_device_heartbeat()[0], 200)
        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "https://example.test/api/handheld/device-heartbeat")
        self.assertEqual(req.get_header("Authorization"), "Bearer session-secret")
        self.assertEqual(req.get_header("Content-type"), "application/json")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)
        import json
        self.assertEqual(json.loads(req.data), {
            "device_id": "SLR-RPI-001", "device_label": "Reader Unit 01",
            "user_agent": f"slr-reader/{APP_VERSION} raspberry-pi",
        })

    def test_login_immediate_interval_and_single_in_flight_worker(self):
        view, dal = self._view()
        threads = []

        def make_thread(**kwargs):
            thread = FakeThread(**kwargs)
            threads.append(thread)
            return thread

        with patch("src.qt_hybrid_app.threading.Thread", side_effect=make_thread):
            self._login(view)
            self.assertTrue(view._heartbeat_timer.active)
            self.assertEqual(len(threads), 1)
            view._start_heartbeat()
            self.assertEqual(len(threads), 1)
            threads[0].finish()
            self.assertEqual(dal.sent, 1)
            view._start_heartbeat()  # The one-minute timer callback.
            self.assertEqual(len(threads), 2)
            threads[1].finish()
            self.assertEqual(dal.sent, 2)

    def test_authenticated_login_still_heartbeats_when_automatic_sync_is_disabled(self):
        view, dal = self._view()
        view._sync_dal = None
        threads = []
        with patch("src.qt_hybrid_app.threading.Thread", side_effect=lambda **kw: threads.append(FakeThread(**kw)) or threads[-1]), patch(
            "src.qt_hybrid_app.get_latest_receipt_print", return_value=None
        ), patch("src.qt_hybrid_app.QTimer.singleShot"):
            AppBridge.set_user(
                view, {"account_id": 12, "username": "reader", "session_token": "session-secret"}, dal,
            )
            self.assertEqual(len(threads), 1)
            threads[0].finish()
        self.assertEqual(dal.sent, 1)
        self.assertEqual(dal.sessions[-1], ("session-secret", "12"))

    def test_reconnect_sends_fresh_heartbeat_and_logout_stops_worker(self):
        view, dal = self._view()
        threads = []
        with patch("src.qt_hybrid_app.threading.Thread", side_effect=lambda **kw: threads.append(FakeThread(**kw)) or threads[-1]):
            self._login(view)
            threads[0].finish()
            AppBridge._set_wifi_status(view, "Status: Disconnected", "gray")
            self.assertEqual(len(threads), 1)
            AppBridge._set_wifi_status(view, "Status: Connected to Wi-Fi", "green")
            self.assertEqual(len(threads), 2)
            threads[1].finish()
            with patch("src.qt_hybrid_app.clear_current_meter_reader"):
                AppBridge.clear_user(view)
            self.assertFalse(view._heartbeat_timer.active)
            self.assertEqual(dal.sessions[-1], (None, None))
            view._start_heartbeat()
            self.assertEqual(len(threads), 2)

    def test_network_failure_does_not_block_reading_and_retries_next_tick(self):
        view, dal = self._view()
        dal.responses = [RuntimeError("connection unavailable"), (200, {})]
        threads = []
        with patch("src.qt_hybrid_app.threading.Thread", side_effect=lambda **kw: threads.append(FakeThread(**kw)) or threads[-1]):
            self._login(view)
            threads[0].finish()
            self.assertIn("Device heartbeat warning", dal.audit[-1][1])
            self.assertEqual(dal.saveMeterReading({"reading_id": "r1"})["status"], "queued")
            view._start_heartbeat()
            threads[1].finish()
            self.assertEqual(dal.sent, 2)

    def test_401_reauth_400_config_and_429_server_backoff(self):
        for status in (401, 400, 429, 503):
            with self.subTest(status=status):
                view, dal = self._view()
                dal.setAuthenticatedSession("session-secret", 12)
                view._heartbeat_dal = dal
                view._heartbeat_authenticated = True
                view._heartbeat_timer.start()
                with patch("src.qt_hybrid_app.time.monotonic", return_value=100):
                    AppBridge._finish_heartbeat(view, 0, status, {"message": "bad session-secret"})
                    if status == 401:
                        self.assertEqual(len(view.sessionExpired.calls), 1)
                        self.assertFalse(view._heartbeat_timer.active)
                    elif status == 400:
                        self.assertTrue(view._heartbeat_config_invalid)
                        self.assertIn("bad [redacted]", dal.audit[-1][1])
                    else:
                        self.assertEqual(view._heartbeat_next_allowed, 220)
                        self.assertIn("retry in 120s", dal.audit[-1][1])
                self.assertNotIn("session-secret", str(dal.audit))

    def test_expired_session_returns_to_existing_login_flow(self):
        events = []
        window = SimpleNamespace(
            _on_logout_requested=lambda: events.append("logout"),
            login_page=SimpleNamespace(bridge=SimpleNamespace(
                show_session_expired=lambda: events.append("login notice")
            )),
        )
        HybridMainWindow._on_session_expired(window)
        self.assertEqual(events, ["logout", "login notice"])

    def test_backoff_blocks_reconnect_until_retry_window(self):
        view, dal = self._view()
        threads = []
        with patch("src.qt_hybrid_app.threading.Thread", side_effect=lambda **kw: threads.append(FakeThread(**kw)) or threads[-1]):
            with patch("src.qt_hybrid_app.time.monotonic", return_value=100):
                self._login(view)
                dal.responses = [(429, {"error": "rate limited"})]
                threads[0].finish()
                AppBridge._set_wifi_status(view, "Status: Connected to Wi-Fi", "green")
                self.assertEqual(len(threads), 1)
            with patch("src.qt_hybrid_app.time.monotonic", return_value=220):
                view._start_heartbeat()
                self.assertEqual(len(threads), 2)

    def test_configuration_error_stops_repeated_heartbeats(self):
        view, dal = self._view()
        threads = []
        dal.responses = [(400, {"message": "invalid device_id"})]
        with patch("src.qt_hybrid_app.threading.Thread", side_effect=lambda **kw: threads.append(FakeThread(**kw)) or threads[-1]):
            self._login(view)
            threads[0].finish()
            self.assertFalse(view._heartbeat_timer.active)
            AppBridge._set_wifi_status(view, "Status: Connected to Wi-Fi", "green")
            self.assertEqual(len(threads), 1)


if __name__ == "__main__":
    unittest.main()

import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib import error, request

from src.handheld_sync import BackendApiClient, SyncConfig
from src.qt_hybrid_app import AppBridge


class BackendConnectionTests(unittest.TestCase):
    def test_schedule_download_accepts_response_slower_than_old_five_second_limit(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(5.2)
                body = json.dumps([{"schedule_id": 7}]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def log_message(self, *_args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                client = BackendApiClient(SyncConfig(
                    backend_api_base_url=f"http://127.0.0.1:{server.server_port}/api",
                ))
                local_opener = request.build_opener(request.ProxyHandler({}))
                with patch("src.handheld_sync.request.urlopen", local_opener.open):
                    self.assertEqual(
                        client.load_reading_schedules(12, "2026-11-01", "2026-11-30"),
                        [{"schedule_id": 7}],
                    )
            finally:
                server.shutdown()
                worker.join(timeout=2)

    def test_timed_out_upload_is_not_blindly_repeated_and_identifies_request(self):
        client = BackendApiClient(SyncConfig(backend_api_base_url="https://example.test/api"))
        client.set_authenticated_session("private-session", 12)
        with patch("src.handheld_sync.request.urlopen", side_effect=error.URLError(TimeoutError("timed out"))) as transport:
            status, response = client._req(
                "POST", "/api/handheld/reading-bundles", payload={"reading_id": "same-reading"},
            )
        self.assertEqual(status, 0)
        self.assertIn("30s", response["error"])
        self.assertIn("POST /api/handheld/reading-bundles", response["error"])
        self.assertNotIn("private-session", response["error"])
        transport.assert_called_once()

    def test_configurable_request_timeout_is_validated(self):
        values = {
            "HANDHELD_DEVICE_ID": "READER-TEST",
            "BACKEND_API_BASE_URL": "https://example.test/api",
        }
        with patch.dict(os.environ, values, clear=True), patch("src.handheld_sync.load_dotenv", return_value=True):
            self.assertEqual(SyncConfig.from_env().api_timeout_seconds, 30)
            os.environ["BACKEND_API_TIMEOUT_SECONDS"] = "45"
            self.assertEqual(SyncConfig.from_env().api_timeout_seconds, 45)
            for value in ("0", "4", "61", "nan", "inf", "text"):
                with self.subTest(value=value):
                    os.environ["BACKEND_API_TIMEOUT_SECONDS"] = value
                    with self.assertRaisesRegex(RuntimeError, "BACKEND_API_TIMEOUT_SECONDS"):
                        SyncConfig.from_env()

    def test_health_check_keeps_a_shorter_limit_than_data_requests(self):
        client = BackendApiClient(SyncConfig(backend_api_base_url="https://example.test/api"))
        with patch("src.handheld_sync.request.urlopen", side_effect=TimeoutError("timed out")) as transport:
            self.assertFalse(client.is_online())
        self.assertEqual(transport.call_args.kwargs["timeout"], 10)
        self.assertIn("GET /health", client.last_health_error)
        self.assertIn("10s", client.last_health_error)

    def test_configured_limit_reaches_data_transport(self):
        client = BackendApiClient(SyncConfig(
            backend_api_base_url="https://example.test/api", api_timeout_seconds=45,
        ))
        with patch("src.handheld_sync.request.urlopen", side_effect=TimeoutError("timed out")) as transport:
            with self.assertRaisesRegex(RuntimeError, "45s.*GET /api/reading-schedules"):
                client.load_reading_schedules(12, "2026-11-01", "2026-11-30")
        self.assertEqual(transport.call_args.kwargs["timeout"], 45)

    def test_ui_snapshot_refresh_starts_background_probe_without_network_wait(self):
        dal = Mock()
        view = SimpleNamespace(
            _sync_dal=dal, _start_backend_probe=Mock(), _emit_sync_state=Mock(),
        )
        AppBridge._refresh_sync_snapshot(view)
        view._start_backend_probe.assert_called_once()
        dal.get_sync_snapshot.assert_not_called()

    def test_clock_rechecks_backend_without_requiring_wifi_to_disconnect(self):
        view = SimpleNamespace(statusTimeChanged=Mock(), _start_backend_probe=Mock())
        AppBridge._tick_status_clock(view)
        view._start_backend_probe.assert_called_once()

    def test_background_probe_does_not_overlap_a_slow_probe(self):
        view = SimpleNamespace(_sync_dal=Mock(), _backend_probe_in_flight=True)
        with patch("src.qt_hybrid_app.threading.Thread") as worker:
            AppBridge._start_backend_probe(view)
        worker.assert_not_called()
        view._sync_dal.get_sync_snapshot.assert_not_called()

    def test_background_probe_recovers_after_timeout_with_auto_sync_disabled(self):
        dal = Mock()
        dal.get_recent_audit_entries.return_value = []
        view = SimpleNamespace(
            _sync_dal=dal, _backend_probe_in_flight=False,
            _backend_status="Offline", _backend_endpoint="https://example.test/api",
            _auto_sync_enabled=False, _start_heartbeat=Mock(), _emit_sync_state=Mock(),
            backendProbeFinished=Mock(), syncLogsChanged=Mock(), backendLogsChanged=Mock(),
        )
        with patch("src.qt_hybrid_app.threading.Thread") as worker:
            worker.return_value.start.side_effect = lambda: worker.call_args.kwargs["target"]()
            for online in (False, True):
                with self.subTest(online=online):
                    dal.get_sync_snapshot.return_value = {
                        "status": "Online" if online else "Offline", "backend_online": online,
                        "backend_health_error": "" if online else "Request timed out after 10s waiting for GET /health.",
                    }
                    AppBridge._start_backend_probe(view)
                    self.assertTrue(view._backend_probe_in_flight)
                    snapshot = view.backendProbeFinished.emit.call_args.args[0]
                    AppBridge._refresh_sync_snapshot(view, snapshot)
                    self.assertFalse(view._backend_probe_in_flight)
                    self.assertEqual(view._backend_status, "Online" if online else "Offline")
        view._start_heartbeat.assert_called_once()
        dal.syncPendingReadings.assert_not_called()


if __name__ == "__main__":
    unittest.main()

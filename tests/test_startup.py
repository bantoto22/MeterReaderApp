import gc
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import database
from src.qt_hybrid_app import HybridMainWindow, LoginBridge, run_qt_hybrid


class StartupTests(unittest.TestCase):
    def test_window_only_builds_login_before_scheduling_storage_preparation(self):
        page = SimpleNamespace(bridge=Mock())
        window = SimpleNamespace(stack=Mock(), _on_login_success=Mock())
        with patch("src.qt_hybrid_app.LoginPage", return_value=page), patch(
            "src.qt_hybrid_app.MainContainerPage"
        ) as workspace, patch("src.qt_hybrid_app.QTimer.singleShot") as schedule, patch(
            "src.qt_hybrid_app.init_db"
        ) as init_db:
            HybridMainWindow._init_login_page(window)
        self.assertIsNone(window.main_page)
        window.stack.addWidget.assert_called_once_with(page)
        workspace.assert_not_called()
        init_db.assert_not_called()
        schedule.assert_called_once_with(0, page.bridge.prepare_database)

    def test_entrypoint_shows_window_without_waiting_for_database_or_backend(self):
        app, window = Mock(), Mock()
        app.exec.return_value = 0
        with patch("src.qt_hybrid_app.SyncConfig.from_env"), patch(
            "src.qt_hybrid_app.QApplication.instance", return_value=app
        ), patch("src.qt_hybrid_app.HybridMainWindow", return_value=window), patch(
            "src.qt_hybrid_app.QTimer.singleShot"
        ), patch("src.qt_hybrid_app.init_db") as init_db, patch(
            "src.qt_hybrid_app.HandheldSyncDataAccess.from_env"
        ) as backend:
            self.assertEqual(run_qt_hybrid(), 0)
        window.show.assert_called_once()
        app.aboutToQuit.connect.assert_called_once_with(window.stop_background_work)
        init_db.assert_not_called()
        backend.assert_not_called()

    def test_slow_storage_preparation_does_not_block_login_bridge_or_run_twice(self):
        bridge = LoginBridge()
        with patch("src.qt_hybrid_app.threading.Thread") as worker, patch(
            "src.qt_hybrid_app.init_db"
        ) as init_db, patch("src.qt_hybrid_app.HandheldSyncDataAccess.from_env") as backend:
            bridge.prepare_database()
            bridge.prepare_database()
            bridge.attemptLogin("reader", "password")
            worker.assert_called_once()
            init_db.assert_not_called()
            backend.assert_not_called()
            self.assertTrue(bridge.loginBusy)
            self.assertEqual(bridge.loginStatus, "Preparing device...")
            worker.call_args.kwargs["target"]()
            init_db.assert_called_once()
        self.assertFalse(bridge.loginBusy)
        self.assertEqual(bridge.loginStatus, "Log In")
        self.assertTrue(bridge._database_ready)

    def test_storage_failure_is_visible_and_can_retry_without_credentials(self):
        bridge = LoginBridge()
        with patch("src.qt_hybrid_app.threading.Thread") as worker, patch(
            "src.qt_hybrid_app.init_db", side_effect=[RuntimeError("storage unavailable"), None]
        ):
            bridge.prepare_database()
            worker.call_args.kwargs["target"]()
            self.assertFalse(bridge.loginBusy)
            self.assertFalse(bridge._database_ready)
            self.assertEqual(bridge.loginStatus, "Retry setup")
            self.assertIn("storage unavailable", bridge.errorMessage)
            bridge.attemptLogin("", "")
            worker.call_args.kwargs["target"]()
        self.assertTrue(bridge._database_ready)
        self.assertEqual(bridge.errorMessage, "")

    def window(self):
        return SimpleNamespace(
            main_page=None, login_page=SimpleNamespace(bridge=Mock()), stack=Mock(),
            _on_logout_requested=Mock(), _on_session_expired=Mock(),
        )

    def test_workspace_is_created_after_login_and_reused_for_next_login(self):
        window = self.window()
        page = SimpleNamespace(bridge=Mock())
        with patch("src.qt_hybrid_app.MainContainerPage", return_value=page) as factory:
            HybridMainWindow._complete_login_success(window, {"id": 12})
            HybridMainWindow._complete_login_success(window, {"id": 13})
        factory.assert_called_once()
        window.stack.addWidget.assert_called_once_with(page)
        page.bridge.logoutRequested.connect.assert_called_once()
        self.assertEqual(page.bridge.set_user.call_count, 2)
        window.stack.setCurrentWidget.assert_called_with(page)

    def test_workspace_failure_leaves_visible_login_and_retry_available(self):
        window = self.window()
        with patch("src.qt_hybrid_app.MainContainerPage", side_effect=RuntimeError("QML load failed")):
            HybridMainWindow._complete_login_success(window, {"id": 12})
        window.stack.setCurrentWidget.assert_called_once_with(window.login_page)
        window.login_page.bridge._finish_login_attempt.assert_called_once_with(
            False, None, "Unable to open reading screen: QML load failed",
        )
        window.login_page.bridge.set_workspace_loading.assert_called_once_with(False)

    def test_close_before_first_login_does_not_require_reading_screen(self):
        HybridMainWindow.stop_background_work(SimpleNamespace(main_page=None))
        page = SimpleNamespace(bridge=Mock())
        HybridMainWindow.stop_background_work(SimpleNamespace(main_page=page))
        page.bridge.stop_heartbeat.assert_called_once()


class StartupDatabaseTests(unittest.TestCase):
    def test_failed_initialization_releases_connection_and_rolls_back_for_retry(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            database, "_db_path", return_value=str(Path(directory) / "meter.db")
        ):
            database.init_db()

            def failed_setup(conn):
                conn.execute("INSERT INTO zones(name) VALUES('Incomplete setup')")
                raise RuntimeError("setup interrupted")

            with patch.object(database, "_initialize_database", side_effect=failed_setup):
                with self.assertRaisesRegex(RuntimeError, "setup interrupted"):
                    database.init_db()
            database.init_db()
            conn = database.get_connection()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM zones").fetchone()[0], 0)
            finally:
                conn.close()
                gc.collect()

    def test_latest_reading_repair_uses_index_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            database, "_db_path", return_value=str(Path(directory) / "meter.db")
        ):
            database.init_db()
            conn = database.get_connection()
            try:
                conn.execute("INSERT INTO zones(id,name) VALUES(1,'Test Zone')")
                conn.execute("INSERT INTO consumers(id,meter_no,acct_no,name,zone_id,previous_reading) VALUES(1,'TEST-METER','TEST-ACCOUNT','Test Consumer',1,0)")
                conn.executemany(
                    "INSERT INTO readings(consumer_id,present_reading,consumption,reading_date) VALUES(1,?,0,?)",
                    [(30, "2026-11-02"), (40, "2026-11-02"), (20, "2026-11-01")],
                )
                conn.commit()
                history = [tuple(row) for row in conn.execute("SELECT * FROM readings ORDER BY id")]
            finally:
                conn.close()
            database.init_db()
            conn = database.get_connection()
            try:
                self.assertEqual(conn.execute("SELECT previous_reading FROM consumers WHERE id=1").fetchone()[0], 40)
                self.assertEqual(history, [tuple(row) for row in conn.execute("SELECT * FROM readings ORDER BY id")])
                plan = conn.execute(
                    "EXPLAIN QUERY PLAN SELECT present_reading FROM readings WHERE consumer_id=? ORDER BY reading_date DESC,id DESC LIMIT 1", (1,),
                ).fetchall()
                self.assertTrue(any("SEARCH" in row[3] and "idx_readings_consumer_latest" in row[3] for row in plan))
                self.assertFalse(any("TEMP B-TREE" in row[3] for row in plan))
            finally:
                conn.close()
                gc.collect()


if __name__ == "__main__":
    unittest.main()

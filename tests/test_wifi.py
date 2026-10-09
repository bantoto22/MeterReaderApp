import os
import stat
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.wifi import connected_wifi_ssid, connect_wifi_network, parse_wifi_scan, split_nmcli_fields
from src.qt_hybrid_app import AppBridge


class WifiTests(unittest.TestCase):
    def test_status_uses_actual_ssid_instead_of_saved_profile_name(self):
        with patch("src.wifi._nmcli", return_value="*:Office\\:East\\\\Wing\n:Guest\n"):
            self.assertEqual(connected_wifi_ssid("wlan0", "Renamed profile"), "Office:East\\Wing")

    def test_scan_keeps_security_and_decodes_ssids_without_duplicate_access_points(self):
        rows = parse_wifi_scan(
            r"Office\:East\\Wing:WPA2:58:" + "\n"
            + r"Office\:East\\Wing:WPA2:91:*" + "\n"
            + "Guest:--:70:\nPhone:WPA3:80:\n:WPA2:30:\n"
        )
        self.assertEqual([row["ssid"] for row in rows], ["Guest", "Office:East\\Wing", "Phone"])
        self.assertEqual([row["mode"] for row in rows], ["open", "wpa-psk", "sae"])
        self.assertEqual(rows[1]["security"], "WPA2")
        self.assertTrue(rows[1]["connected"])
        self.assertEqual(rows[1]["signal"], 91)
        self.assertEqual(split_nmcli_fields(r"wlan0:wifi:connected:Office\:East\\Wing"),
                         ["wlan0", "wifi", "connected", "Office:East\\Wing"])

    def _run_connection(self, *, key="wpa-psk", detected="wpa-psk",
                        password="new secret:123", saved=True, fail=False):
        calls, secret_paths = [], []

        def run(args, **kwargs):
            calls.append(args)
            self.assertEqual(kwargs["env"]["LC_ALL"], "C")
            self.assertNotIn(password, args)
            output = ""
            if args[1:5] == ["-t", "-f", "UUID,TYPE", "connection"]:
                output = "other-network:wifi\nsaved-profile:wifi\n" if saved else ""
            elif "connection" in args and "show" in args and "-g" in args:
                output = "Other Network\nwpa-psk\n" if args[-1] == "other-network" else f"Office\\:East\\\\Wing\n{key}\n"
            elif args[1:5] == ["-t", "-f", "DEVICE,TYPE", "device"]:
                output = "eth0:ethernet\nwlan0:wifi\n"
            elif "up" in args:
                if password and detected in {"wpa-psk", "sae"}:
                    path = args[args.index("passwd-file") + 1]
                    secret_paths.append(path)
                    with open(path, encoding="utf-8") as handle:
                        self.assertEqual(handle.read(), f"802-11-wireless-security.psk:{password}\n")
                    if os.name != "nt":
                        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
                if fail:
                    return SimpleNamespace(returncode=1, stdout="", stderr=f"Activation failed: {password}")
            return SimpleNamespace(returncode=0, stdout=output, stderr="")

        with patch("src.wifi.subprocess.run", side_effect=run):
            if fail:
                with self.assertRaises(RuntimeError) as caught:
                    connect_wifi_network("Office:East\\Wing", password, detected_mode=detected)
                self.assertNotIn(password, str(caught.exception))
                self.assertIn("[redacted]", str(caught.exception))
            else:
                connect_wifi_network("Office:East\\Wing", password, detected_mode=detected)
        self.assertTrue(all(not os.path.exists(path) for path in secret_paths))
        return calls

    def test_saved_profile_is_matched_by_ssid_and_activated_by_uuid(self):
        calls = self._run_connection()
        up = next(args for args in calls if "up" in args)
        self.assertEqual(up[:8], ["nmcli", "--wait", "25", "connection", "up", "uuid", "saved-profile", "ifname"])
        modify = next(args for args in calls if "modify" in args)
        self.assertEqual(modify[modify.index("802-11-wireless-security.psk") + 1], "")
        self.assertFalse(any("delete" in args or "down" in args for args in calls))
        self.assertFalse(any("modify" in args and "other-network" in args for args in calls))

    def test_missing_security_is_repaired_with_explicit_key_management(self):
        calls = self._run_connection(key="")
        modify = next(args for args in calls if "modify" in args)
        self.assertEqual(modify[modify.index("802-11-wireless-security.key-mgmt") + 1], "wpa-psk")
        self.assertFalse(any("add" in args for args in calls))

    def test_new_network_has_security_before_activation(self):
        for mode in ("wpa-psk", "sae"):
            with self.subTest(mode=mode):
                calls = self._run_connection(saved=False, detected=mode)
                add = next(args for args in calls if "add" in args)
                up = next(args for args in calls if "up" in args)
                self.assertEqual(add[add.index("802-11-wireless-security.key-mgmt") + 1], mode)
                self.assertEqual(add[add.index("connection.uuid") + 1], up[up.index("uuid") + 1])

    def test_saved_password_can_be_used_without_clearing_it(self):
        calls = self._run_connection(password="")
        self.assertFalse(any("802-11-wireless-security.psk" in args for args in calls))
        self.assertNotIn("passwd-file", next(args for args in calls if "up" in args))

    def test_open_network_does_not_add_a_security_section(self):
        calls = self._run_connection(saved=False, password="", detected="open")
        add = next(args for args in calls if "add" in args)
        self.assertFalse(any("security" in arg for arg in add))

    def test_failed_activation_cleans_up_and_redacts_password(self):
        self._run_connection(fail=True)

    def test_invalid_password_cannot_inject_additional_secrets(self):
        with patch("src.wifi.subprocess.run") as run:
            with self.assertRaises(ValueError):
                connect_wifi_network("Office", "secret\n802-1x.password:injected", detected_mode="wpa-psk")
        run.assert_not_called()

    def test_new_secured_network_requires_password_before_profile_changes(self):
        with patch("src.wifi._saved_wifi_profiles", return_value=[]), patch("src.wifi._nmcli") as run:
            with self.assertRaisesRegex(ValueError, "Enter the Wi-Fi password"):
                connect_wifi_network("Office", "", detected_mode="wpa-psk")
        run.assert_not_called()

    def test_security_mismatch_does_not_modify_profiles(self):
        with patch("src.wifi._saved_wifi_profiles", return_value=[]), patch("src.wifi._nmcli") as run:
            with self.assertRaisesRegex(ValueError, "does not match"):
                connect_wifi_network("Office", "", "open", detected_mode="wpa-psk")
        run.assert_not_called()


class WifiBridgeTests(unittest.TestCase):
    def _view(self):
        view = SimpleNamespace(
            _wifi_busy=False, _wifi_scan_silent=True, _wifi_networks=["Office"],
            _wifi_network_details=[{"ssid": "Office", "mode": "wpa-psk", "security": "WPA2"}],
            _wifi_status="Status: Connected to Office", _wifi_status_color="green",
            wifiNetworksChanged=SimpleNamespace(emit=Mock()),
            wifiStatusChanged=SimpleNamespace(emit=Mock()),
            wifiStatusColorChanged=SimpleNamespace(emit=Mock()),
            wifiBusyChanged=SimpleNamespace(emit=Mock()),
            wifiScanFinished=SimpleNamespace(emit=Mock()),
            alertRequested=SimpleNamespace(emit=Mock()), refreshWifiStatus=Mock(),
            _set_wifi_status=Mock(), _start_backend_probe=Mock(),
        )
        view._set_wifi_busy = lambda *args: AppBridge._set_wifi_busy(view, *args)
        return view

    def test_background_scan_preserves_connected_status(self):
        view = self._view()
        with patch("src.qt_hybrid_app.threading.Thread"):
            AppBridge._start_wifi_scan(view, True)
        self.assertEqual(view._wifi_status, "Status: Connected to Office")
        AppBridge._finish_wifi_scan(view, view._wifi_network_details, "")
        self.assertEqual(view._wifi_status, "Status: Connected to Office")
        view.wifiNetworksChanged.emit.assert_not_called()

    def test_background_scan_failure_retains_network_and_security(self):
        view = self._view()
        AppBridge._finish_wifi_scan(view, [], "Scan timed out")
        self.assertEqual(view._wifi_networks, ["Office"])
        self.assertEqual(view._wifi_network_details[0]["security"], "WPA2")
        self.assertEqual(view._wifi_status, "Status: Connected to Office")

    def test_connection_rechecks_backend_even_when_auto_sync_is_disabled(self):
        view = self._view()
        AppBridge._finish_wifi_connect(view, True, "Phone", "")
        view._start_backend_probe.assert_called_once()
        view._set_wifi_status.assert_called_once_with("Status: Connected to Phone", "#10B981")

    def test_unchanged_status_poll_does_not_reprobe_backend(self):
        view = self._view()
        AppBridge._finish_wifi_connect(view, True, "Office", "status-only")
        view._start_backend_probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()

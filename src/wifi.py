"""NetworkManager Wi-Fi scanning and profile activation for the handheld."""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid


def split_nmcli_fields(line: str) -> list[str]:
    """Decode terse nmcli fields, including escaped colons and backslashes."""
    fields, value = [], []
    escaped = False
    for char in line:
        if escaped:
            value.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(value))
            value = []
        else:
            value.append(char)
    if escaped:
        value.append("\\")
    fields.append("".join(value))
    return fields


def security_mode(security: str) -> str:
    value = security.upper().strip()
    if value in {"", "--", "OPEN"}:
        return "open"
    if "802.1X" in value or "EAP" in value:
        return "enterprise"
    if "WEP" in value:
        return "wep"
    if "OWE" in value:
        return "owe"
    if "WPA3" in value and "WPA2" not in value and "WPA1" not in value:
        return "sae"
    if "WPA" in value:
        return "wpa-psk"
    return "unknown"


def parse_wifi_scan(output: str) -> list[dict]:
    networks = {}
    for line in output.splitlines():
        parts = split_nmcli_fields(line)
        if len(parts) != 4 or not parts[0]:
            continue
        ssid, security, signal, active = parts
        try:
            strength = int(signal)
        except ValueError:
            strength = 0
        row = {"ssid": ssid, "security": security or "Open",
               "mode": security_mode(security), "signal": strength, "connected": active == "*"}
        previous = networks.get(ssid)
        if previous is None or (row["connected"], strength) > (previous["connected"], previous["signal"]):
            networks[ssid] = row
    return sorted(networks.values(), key=lambda row: row["ssid"].casefold())


def _nmcli(*args: str, timeout: int = 10, password: str = "") -> str:
    try:
        result = subprocess.run(
            ["nmcli", *args], capture_output=True, text=True, timeout=timeout,
            check=False, env={**os.environ, "LC_ALL": "C"},
        )
    except FileNotFoundError as exc:
        raise RuntimeError("NetworkManager utility 'nmcli' is not installed.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Wi-Fi operation timed out. Check the signal and try again.") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "Wi-Fi operation failed.").strip()
        if password:
            detail = detail.replace(password, "[redacted]")
        if "secrets were required" in detail.lower() or "no secrets" in detail.lower():
            detail = "This network needs a Wi-Fi password. Enter it in Password and try again."
        elif "not authorized" in detail.lower() or "permission denied" in detail.lower():
            detail = "The app user is not authorized to manage Wi-Fi. Check NetworkManager permissions on the Pi."
        raise RuntimeError(detail)
    return result.stdout


def scan_wifi_networks(*, rescan: bool = True) -> list[dict]:
    return parse_wifi_scan(_nmcli(
        "-t", "-f", "SSID,SECURITY,SIGNAL,IN-USE", "device", "wifi", "list",
        "--rescan", "yes" if rescan else "auto", timeout=20,
    ))


def connected_wifi_ssid(adapter: str, profile_name: str) -> str:
    output = _nmcli("-t", "-f", "IN-USE,SSID", "device", "wifi", "list",
                    "ifname", adapter, "--rescan", "no")
    for line in output.splitlines():
        fields = split_nmcli_fields(line)
        if len(fields) == 2 and fields[0] == "*" and fields[1]:
            return fields[1]
    return profile_name


def _saved_wifi_profiles(ssid: str) -> list[tuple[str, str]]:
    profiles = []
    listing = _nmcli("-t", "-f", "UUID,TYPE", "connection", "show")
    for line in listing.splitlines():
        fields = split_nmcli_fields(line)
        if len(fields) != 2 or fields[1] not in {"wifi", "802-11-wireless"}:
            continue
        profile_uuid = fields[0]
        output = _nmcli(
            "-g", "802-11-wireless.ssid,802-11-wireless-security.key-mgmt",
            "connection", "show", "uuid", profile_uuid,
        ).splitlines()
        if output and split_nmcli_fields(output[0])[0] == ssid:
            key_mgmt = output[1].strip() if len(output) > 1 else ""
            profiles.append((profile_uuid, "" if key_mgmt == "--" else key_mgmt))
    return profiles


def connect_wifi_network(ssid: str, password: str, security: str = "auto", *, detected_mode: str = "") -> None:
    """Set explicit security and activate the matching profile by UUID.

    Passwords are supplied through a private temporary secret file, never argv.
    Profiles for other networks are retained.
    """
    if not ssid.strip():
        raise ValueError("Enter or select a Wi-Fi network first.")
    if any(char in password for char in "\r\n\0"):
        raise ValueError("The Wi-Fi password must not contain a line break or null character.")
    if security not in {"auto", "open", "wpa-psk", "sae"}:
        raise ValueError("Select Automatic, WPA/WPA2 Personal, WPA3 Personal, or Open security.")
    profiles = _saved_wifi_profiles(ssid)
    mode = security
    if mode == "auto":
        mode = detected_mode
        if not mode or mode == "unknown":
            networks = scan_wifi_networks(rescan=False)
            mode = next((row["mode"] for row in networks if row["ssid"] == ssid), "")
        if not mode or mode == "unknown":
            mode = next((key for _, key in profiles if key), "")
        if not mode:
            raise ValueError("Security could not be detected. Scan again or select the network's Security type.")
    if mode not in {"open", "wpa-psk", "sae", "owe"}:
        raise ValueError("This network needs WEP or enterprise settings. Configure it in Raspberry Pi network settings.")
    if security != "auto" and detected_mode and detected_mode not in {"unknown", mode}:
        raise ValueError("The selected Security does not match this network. Select Automatic or scan again.")
    if password and mode == "wpa-psk" and not (
        8 <= len(password) <= 63 or (len(password) == 64 and all(c in "0123456789abcdefABCDEF" for c in password))
    ):
        raise ValueError("WPA/WPA2 passwords need 8–63 characters, or a 64-digit hexadecimal key.")
    compatible = next((item for item in profiles if item[1] == ("" if mode == "open" else mode)), None)
    # Repair an incomplete saved security section instead of depending on a GUI secret agent.
    if compatible is None and mode in {"wpa-psk", "sae"} and password:
        compatible = next((item for item in profiles if not item[1]), None)
    if compatible is None and mode in {"wpa-psk", "sae"} and not password:
        raise ValueError("Enter the Wi-Fi password for this network.")
    devices = _nmcli("-t", "-f", "DEVICE,TYPE", "device", "status")
    adapter = next((fields[0] for line in devices.splitlines()
                    if len(fields := split_nmcli_fields(line)) == 2 and fields[1] == "wifi"), "")
    if not adapter:
        raise RuntimeError("No Wi-Fi adapter detected on the Raspberry Pi.")
    profile_uuid = compatible[0] if compatible else str(uuid.uuid4())
    security_args = [] if mode == "open" else ["802-11-wireless-security.key-mgmt", mode]
    if mode in {"wpa-psk", "sae"} and password:
        security_args.extend(["802-11-wireless-security.psk", "",
                              "802-11-wireless-security.psk-flags", "0"])
    if compatible:
        if security_args:
            _nmcli("connection", "modify", "uuid", profile_uuid, *security_args)
    else:
        _nmcli("connection", "add", "type", "wifi", "ifname", adapter,
               "con-name", f"Meter Reader {ssid}", "connection.uuid", profile_uuid,
               "ssid", ssid, *security_args)
    command = ["--wait", "25", "connection", "up", "uuid", profile_uuid, "ifname", adapter]
    secret_path = None
    try:
        if password and mode in {"wpa-psk", "sae"}:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as secret_file:
                secret_path = secret_file.name
                secret_file.write(f"802-11-wireless-security.psk:{password}\n")
            command.extend(["passwd-file", secret_path])
        _nmcli(*command, timeout=30, password=password)
    finally:
        if secret_path:
            os.unlink(secret_path)

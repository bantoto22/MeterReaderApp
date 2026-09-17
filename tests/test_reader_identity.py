import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import database
from src.handheld_sync import BackendApiClient, SyncConfig
from src.reader_identity import reader_display_name
from src.receipt import build_receipt_text


class ReaderIdentityTests(unittest.TestCase):
    def test_online_real_name_survives_offline_login(self):
        profiles = [
            {"fullName": "Juan Dela Cruz"},
            {"full_name": "Juan Dela Cruz"},
            {"name": "Juan Dela Cruz"},
            {"first_name": "Juan", "middle_name": "Dela", "last_name": "Cruz"},
            {"firstName": "Juan", "middleName": "Dela", "lastName": "Cruz"},
            {"full_name": "reader1", "name": "Juan Dela Cruz"},
            {"full_name": "Field Reader", "name": "Juan Dela Cruz"},
            {"Full_Name": "Juan Dela Cruz"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(database, "_db_path", return_value=str(Path(directory) / "meter.db")):
                database.init_db()
                client = BackendApiClient(SyncConfig(backend_api_base_url="https://example.test"))
                for profile in profiles:
                    with self.subTest(profile=profile):
                        payload = {"success": True, "user": {
                            "id": 12, "username": "reader1", "role_id": 3, **profile,
                        }}
                        with patch.object(client, "_req", return_value=(200, payload)):
                            user = client.authenticate_meter_reader("reader1", "secret")
                        self.assertEqual(user["full_name"], "Juan Dela Cruz")
                        database.cache_meter_reader_credentials(user, "secret")
                        cached = database.authenticate_user("reader1", "secret")
                        self.assertEqual(cached["full_name"], "Juan Dela Cruz")
                        receipt = build_receipt_text(
                            {
                                "classification_id": 1,
                                "classification_name": "Residential",
                                "minimum_cubic": 10,
                                "minimum_rate": 100,
                                "excess_rate_per_cubic": 15,
                                "due_days": 15,
                            },
                            0, 1, "None", reader_display_name(cached),
                        )
                        self.assertIn("Reader         : Juan Dela Cruz", receipt)
                        self.assertNotIn("reader1", receipt)
                        self.assertNotIn("Field Reader", receipt)

    def test_missing_or_legacy_name_uses_username(self):
        for profile in (
            None,
            {"username": "reader1"},
            {"username": "reader1", "full_name": "reader1", "name": "reader1"},
            {"username": "reader1", "full_name": "  "},
            {"username": "reader1", "full_name": "Field Reader"},
            {"username": "Juan.DelaCruz", "full_name": ""},
        ):
            with self.subTest(profile=profile):
                self.assertEqual(reader_display_name(profile), (profile or {}).get("username", ""))

    def test_receipt_allows_missing_name_without_a_placeholder(self):
        for name in ("", "Field Reader", " field reader ", "N/A", "User"):
            with self.subTest(name=name):
                receipt = build_receipt_text(
                    {
                        "classification_id": 1,
                        "classification_name": "Residential",
                        "minimum_cubic": 10,
                        "minimum_rate": 100,
                        "excess_rate_per_cubic": 15,
                        "due_days": 15,
                    },
                    0, 1, "None", name,
                )
                reader_line = next(line for line in receipt.splitlines() if line.strip().startswith("Reader"))
                self.assertEqual(reader_line, " Reader         :")
                self.assertIn("TOTAL DUE", receipt)

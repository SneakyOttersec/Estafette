from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from cryptography.fernet import Fernet
from estafette_service.config import (
    DistributionSettings,
    GoogleClientSettings,
    StorageSettings,
)
from estafette_service.distributor import deliver
from estafette_service.security import TokenCipher


class MemoryStore:
    def __init__(self, registrations=None) -> None:
        self.registrations = registrations or {}
        self.delivery_updates: dict[str, dict] = {}

    def get(self, user_id: str):
        return self.registrations.get(user_id)

    def save(self, user_id: str, *, folder_id: str, encrypted_refresh_token: str):
        self.registrations[user_id] = {
            "user_id": user_id,
            "folder_id": folder_id,
            "encrypted_refresh_token": encrypted_refresh_token,
            "active": True,
        }

    def delete(self, user_id: str):
        self.registrations.pop(user_id, None)

    def list_active(self):
        return [
            registration
            for registration in self.registrations.values()
            if registration.get("active", True)
        ]

    def record_delivery(
        self,
        user_id: str,
        *,
        filenames=None,
        error=None,
        reconnect_required=False,
    ):
        self.delivery_updates[user_id] = {
            "filenames": filenames,
            "error": error,
            "reconnect_required": reconnect_required,
        }


def distribution_settings() -> DistributionSettings:
    return DistributionSettings(
        google=GoogleClientSettings("client-id", "client-secret"),
        storage=StorageSettings("project-id"),
        token_encryption_key="unused-in-this-test",
    )


class TokenCipherTests(TestCase):
    def test_refresh_token_round_trip(self) -> None:
        cipher = TokenCipher(Fernet.generate_key())
        ciphertext = cipher.encrypt("refresh-token-value")

        self.assertNotIn("refresh-token-value", ciphertext)
        self.assertEqual(cipher.decrypt(ciphertext), "refresh-token-value")

    def test_invalid_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Fernet key"):
            TokenCipher("not-a-fernet-key")


class DeliveryTests(TestCase):
    def test_delivers_each_pdf_and_records_success(self) -> None:
        cipher = TokenCipher(Fernet.generate_key())
        store = MemoryStore(
            {
                "user-1": {
                    "user_id": "user-1",
                    "folder_id": "folder-1",
                    "encrypted_refresh_token": cipher.encrypt("token-1"),
                    "active": True,
                }
            }
        )
        uploads = []

        def uploader(credentials, folder_id, path):
            uploads.append((credentials.refresh_token, folder_id, path.name))
            return f"id-{path.name}"

        with TemporaryDirectory() as tmp:
            pdfs = [
                Path(tmp) / "OFFENSIVE_03_09_2026.pdf",
                Path(tmp) / "GENERAL_03_09_2026.pdf",
            ]
            for pdf in pdfs:
                pdf.write_bytes(b"%PDF-test")

            result = deliver(
                pdfs,
                settings=distribution_settings(),
                store=store,
                cipher=cipher,
                uploader=uploader,
            )

        self.assertEqual(result.registrations, 1)
        self.assertEqual(result.delivered, 1)
        self.assertEqual(result.failed, 0)
        self.assertEqual(
            uploads,
            [
                ("token-1", "folder-1", "OFFENSIVE_03_09_2026.pdf"),
                ("token-1", "folder-1", "GENERAL_03_09_2026.pdf"),
            ],
        )
        self.assertEqual(
            store.delivery_updates["user-1"]["filenames"],
            ["OFFENSIVE_03_09_2026.pdf", "GENERAL_03_09_2026.pdf"],
        )

    def test_one_failed_registration_does_not_stop_other_users(self) -> None:
        cipher = TokenCipher(Fernet.generate_key())
        store = MemoryStore(
            {
                "broken": {
                    "user_id": "broken",
                    "folder_id": "bad-folder",
                    "encrypted_refresh_token": cipher.encrypt("bad-token"),
                    "active": True,
                },
                "working": {
                    "user_id": "working",
                    "folder_id": "good-folder",
                    "encrypted_refresh_token": cipher.encrypt("good-token"),
                    "active": True,
                },
            }
        )

        def uploader(credentials, folder_id, path):
            if folder_id == "bad-folder":
                raise RuntimeError("permission revoked")
            return "file-id"

        with TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "GENERAL_03_09_2026.pdf"
            pdf.write_bytes(b"%PDF-test")
            result = deliver(
                [pdf],
                settings=distribution_settings(),
                store=store,
                cipher=cipher,
                uploader=uploader,
            )

        self.assertEqual(result.delivered, 1)
        self.assertEqual(result.failed, 1)
        self.assertIn("permission revoked", store.delivery_updates["broken"]["error"])
        self.assertIsNone(store.delivery_updates["working"]["error"])

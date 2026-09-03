from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from cryptography.fernet import Fernet
from estafette_service.config import (
    GoogleClientSettings,
    StorageSettings,
    WebSettings,
)
from estafette_service.security import TokenCipher
from estafette_service.web import create_app
from test_drive_delivery import MemoryStore


def web_settings(key: bytes) -> WebSettings:
    return WebSettings(
        google=GoogleClientSettings("client-id", "client-secret"),
        storage=StorageSettings("project-id"),
        token_encryption_key=key.decode("ascii"),
        session_secret="test-session-secret",
        oauth_redirect_uri="http://localhost/auth/callback",
        public_site_url="https://sneakyottersec.github.io/Estafette/",
        drive_folder_name="Estafette",
    )


class FakeCredentials:
    id_token = "signed-id-token"
    refresh_token = "refresh-token"
    token = "access-token"
    granted_scopes = ("openid", "https://www.googleapis.com/auth/drive.file")
    scopes = granted_scopes


class FakeCallbackFlow:
    credentials = FakeCredentials()

    def fetch_token(self, authorization_response):
        self.authorization_response = authorization_response


class RegistrationWebTests(TestCase):
    def setUp(self) -> None:
        self.key = Fernet.generate_key()
        self.settings = web_settings(self.key)
        self.store = MemoryStore()
        self.app = create_app(self.settings, self.store)
        self.app.testing = True

    def test_health_check(self) -> None:
        response = self.app.test_client().get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_state_mismatch_is_rejected_before_token_exchange(self) -> None:
        client = self.app.test_client()
        with client.session_transaction() as oauth_session:
            oauth_session["oauth_state"] = "expected"
            oauth_session["oauth_action"] = "connect"
            oauth_session["oauth_nonce"] = "nonce"

        with patch("estafette_service.web.build_oauth_flow") as flow:
            response = client.get("/auth/callback?state=wrong&code=code")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.location,
            "https://sneakyottersec.github.io/Estafette/?error=oauth_failed",
        )
        flow.assert_not_called()

    def test_callback_creates_folder_and_saves_encrypted_refresh_token(self) -> None:
        client = self.app.test_client()
        with client.session_transaction() as oauth_session:
            oauth_session["oauth_state"] = "expected"
            oauth_session["oauth_action"] = "connect"
            oauth_session["oauth_nonce"] = "expected-nonce"

        with (
            patch(
                "estafette_service.web.build_oauth_flow",
                return_value=FakeCallbackFlow(),
            ),
            patch(
                "estafette_service.web.verify_google_id_token",
                return_value={"sub": "google-user-id", "nonce": "expected-nonce"},
            ),
            patch(
                "estafette_service.web.ensure_delivery_folder",
                return_value="drive-folder-id",
            ) as ensure_folder,
        ):
            response = client.get("/auth/callback?state=expected&code=code")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.location,
            "https://sneakyottersec.github.io/Estafette/?connected=1",
        )
        ensure_folder.assert_called_once()
        registration = self.store.get("google-user-id")
        self.assertEqual(registration["folder_id"], "drive-folder-id")
        self.assertNotIn("refresh-token", registration["encrypted_refresh_token"])
        self.assertEqual(
            TokenCipher(self.key).decrypt(registration["encrypted_refresh_token"]),
            "refresh-token",
        )

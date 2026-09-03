"""Google OAuth helpers shared by registration routes."""

from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow

from .config import WebSettings
from .drive import DRIVE_FILE_SCOPE

OPENID_SCOPE = "openid"
OAUTH_SCOPES = [OPENID_SCOPE, DRIVE_FILE_SCOPE]


def build_oauth_flow(settings: WebSettings, *, state: str | None = None) -> Flow:
    client_config = {
        "web": {
            "client_id": settings.google.client_id,
            "client_secret": settings.google.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [settings.oauth_redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=OAUTH_SCOPES, state=state)
    flow.redirect_uri = settings.oauth_redirect_uri
    return flow


def verify_google_id_token(raw_token: str, settings: WebSettings) -> dict:
    return id_token.verify_oauth2_token(
        raw_token,
        Request(),
        audience=settings.google.client_id,
    )

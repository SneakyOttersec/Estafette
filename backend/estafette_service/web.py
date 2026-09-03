"""Flask application for connecting and disconnecting Google Drive."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import requests
from flask import Flask, current_app, redirect, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import WebSettings
from .drive import DRIVE_FILE_SCOPE, ensure_delivery_folder
from .oauth import build_oauth_flow, verify_google_id_token
from .security import TokenCipher
from .storage import FirestoreRegistrationStore, RegistrationStore


def _site_redirect(settings: WebSettings, **query: str) -> str:
    base = settings.public_site_url.rstrip("/") + "/"
    return f"{base}?{urlencode(query)}" if query else base


def _revoke_token(token: str) -> None:
    response = requests.post(
        "https://oauth2.googleapis.com/revoke",
        data={"token": token},
        headers={"content-type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    if response.status_code not in {200, 400}:
        response.raise_for_status()


def create_app(
    settings: WebSettings | None = None,
    store: RegistrationStore | None = None,
) -> Flask:
    settings = settings or WebSettings.from_env()
    store = store or FirestoreRegistrationStore(settings.storage)
    cipher = TokenCipher(settings.token_encryption_key)

    app = Flask(__name__)
    app.secret_key = settings.session_secret
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.oauth_redirect_uri.startswith("https://"),
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.extensions["estafette_settings"] = settings
    app.extensions["estafette_store"] = store

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    def begin_oauth(action: str):
        session.clear()
        nonce = secrets.token_urlsafe(24)
        flow = build_oauth_flow(settings)
        options = {
            "include_granted_scopes": "true",
            "nonce": nonce,
        }
        if action == "connect":
            options.update(access_type="offline", prompt="consent")
        else:
            options.update(access_type="online", prompt="select_account")
        authorization_url, state = flow.authorization_url(**options)
        session["oauth_state"] = state
        session["oauth_nonce"] = nonce
        session["oauth_action"] = action
        return redirect(authorization_url, code=302)

    @app.get("/auth/start")
    def auth_start():
        return begin_oauth("connect")

    @app.get("/auth/disconnect")
    def auth_disconnect():
        return begin_oauth("disconnect")

    @app.get("/auth/callback")
    def auth_callback():
        if request.args.get("error"):
            return redirect(
                _site_redirect(settings, error=request.args["error"]), code=302
            )

        expected_state = session.pop("oauth_state", "")
        supplied_state = request.args.get("state", "")
        if not expected_state or not secrets.compare_digest(
            expected_state, supplied_state
        ):
            return redirect(_site_redirect(settings, error="oauth_failed"), code=302)

        action = session.pop("oauth_action", "connect")
        expected_nonce = session.pop("oauth_nonce", "")
        try:
            flow = build_oauth_flow(settings, state=expected_state)
            flow.fetch_token(authorization_response=request.url)
            credentials = flow.credentials
            if not credentials.id_token:
                raise ValueError("Google did not return an ID token")
            identity = verify_google_id_token(credentials.id_token, settings)
            if not expected_nonce or not secrets.compare_digest(
                str(identity.get("nonce", "")), expected_nonce
            ):
                raise ValueError("Google ID token nonce did not match")
            user_id = str(identity["sub"])

            existing = store.get(user_id)
            if action == "disconnect":
                token_to_revoke = credentials.token
                if existing and existing.get("encrypted_refresh_token"):
                    token_to_revoke = cipher.decrypt(
                        existing["encrypted_refresh_token"]
                    )
                try:
                    _revoke_token(token_to_revoke)
                except Exception:
                    current_app.logger.warning(
                        "Token revocation failed during disconnect",
                        exc_info=True,
                    )
                store.delete(user_id)
                return redirect(_site_redirect(settings, disconnected="1"), code=302)

            granted_scopes = set(credentials.granted_scopes or credentials.scopes or [])
            if DRIVE_FILE_SCOPE not in granted_scopes:
                return redirect(
                    _site_redirect(settings, error="access_denied"), code=302
                )

            refresh_token = credentials.refresh_token
            if not refresh_token and existing:
                encrypted = existing.get("encrypted_refresh_token")
                if encrypted:
                    refresh_token = cipher.decrypt(encrypted)
            if not refresh_token:
                return redirect(
                    _site_redirect(settings, error="missing_refresh_token"), code=302
                )

            folder_id = ensure_delivery_folder(
                credentials,
                name=settings.drive_folder_name,
                existing_folder_id=existing.get("folder_id") if existing else None,
            )
            store.save(
                user_id,
                folder_id=folder_id,
                encrypted_refresh_token=cipher.encrypt(refresh_token),
            )
            return redirect(_site_redirect(settings, connected="1"), code=302)
        except Exception:
            current_app.logger.exception("Google OAuth callback failed")
            return redirect(_site_redirect(settings, error="oauth_failed"), code=302)

    return app

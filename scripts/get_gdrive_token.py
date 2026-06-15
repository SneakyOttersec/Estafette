"""One-time helper: obtain a Google Drive OAuth refresh token.

Run this LOCALLY once (it opens a browser for you to consent). It prints the
values to store as GitHub Actions secrets:
    GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN

Provide the OAuth client either by:
  - env vars GDRIVE_CLIENT_ID + GDRIVE_CLIENT_SECRET, or
  - a Desktop-app client JSON (path as arg, or ./client_secret.json).

Usage:
    pip install google-auth-oauthlib
    GDRIVE_CLIENT_ID=... GDRIVE_CLIENT_SECRET=... python scripts/get_gdrive_token.py
    #   or
    python scripts/get_gdrive_token.py path/to/client_secret.json
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

# drive.file: the pipeline only ever touches files/folders it creates.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def build_flow() -> InstalledAppFlow:
    cid = os.environ.get("GDRIVE_CLIENT_ID")
    csec = os.environ.get("GDRIVE_CLIENT_SECRET")
    if cid and csec:
        config = {
            "installed": {
                "client_id": cid,
                "client_secret": csec,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        return InstalledAppFlow.from_client_config(config, SCOPES)

    secret = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name(
        "client_secret.json"
    )
    if secret.exists():
        return InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)

    print(
        "No client provided. Set GDRIVE_CLIENT_ID + GDRIVE_CLIENT_SECRET, or pass "
        "a Desktop-app client JSON path.",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    flow = build_flow()
    # Opens a browser; offline + consent guarantees a refresh token is returned.
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    if not creds.refresh_token:
        print("\nNo refresh token returned. Revoke prior access and retry with "
              "prompt=consent (already set).", file=sys.stderr)
        sys.exit(1)

    print("\n=== Add these as GitHub repo secrets ===")
    print(f"GDRIVE_CLIENT_ID     = {creds.client_id}")
    print(f"GDRIVE_CLIENT_SECRET = {creds.client_secret}")
    print(f"GDRIVE_REFRESH_TOKEN = {creds.refresh_token}")


if __name__ == "__main__":
    main()

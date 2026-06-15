"""One-time helper: obtain a Google Drive OAuth refresh token.

Run this LOCALLY once (it opens a browser for you to consent). It prints the
three values to store as GitHub Actions secrets:
    GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN

Prerequisites:
  1. In Google Cloud Console: enable the Google Drive API, configure the OAuth
     consent screen (External; add your own Google account as a Test user), then
     create an OAuth client ID of type "Desktop app".
  2. Download its JSON and either pass it as the first argument or save it as
     client_secret.json next to this script.

Usage:
    pip install google-auth-oauthlib
    python scripts/get_gdrive_token.py [path/to/client_secret.json]
"""
from __future__ import annotations

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

# drive.file: the pipeline only ever touches files/folders it creates.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main() -> None:
    secret = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name(
        "client_secret.json"
    )
    if not secret.exists():
        print(f"Client secret JSON not found: {secret}", file=sys.stderr)
        print("Create a Desktop-app OAuth client and download its JSON first.")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    # Opens a browser; access_type=offline + prompt=consent guarantees a refresh token.
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    print("\n=== Add these as GitHub repo secrets ===")
    print(f"GDRIVE_CLIENT_ID     = {creds.client_id}")
    print(f"GDRIVE_CLIENT_SECRET = {creds.client_secret}")
    print(f"GDRIVE_REFRESH_TOKEN = {creds.refresh_token}")


if __name__ == "__main__":
    main()

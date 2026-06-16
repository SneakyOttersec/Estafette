"""Upload the generated PDFs to a Google Drive folder via OAuth (user creds).

Why OAuth and not a service account: a personal Gmail account has no Shared
Drive, and files created by a service account are owned by the (quota-less)
service account, so uploads to a personal Drive fail. Using the user's own
OAuth credentials, the files are owned by the user and use their storage.

Auth (set as GitHub Actions secrets / env vars):
  - GDRIVE_CLIENT_ID
  - GDRIVE_CLIENT_SECRET
  - GDRIVE_REFRESH_TOKEN   (obtained once via scripts/get_gdrive_token.py)

Destination: a folder named GDRIVE_FOLDER_NAME (default "BLOG_INFOSEC_NEWS"),
created in the user's My Drive on first run and reused afterwards.

Each PDF in dist/ is uploaded by name; if a file with that name already exists
in the folder its content is updated (so re-running the same day overwrites that
day's file rather than duplicating it).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from common import DIST_DIR, use_utf8_stdout

# drive.file = access only to files/folders this app creates. Enough to create
# BLOG_INFOSEC_NEWS and manage the PDFs it puts there; nothing else in the Drive.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_FOLDER = "BLOG_INFOSEC_NEWS"


def load_credentials() -> Credentials:
    client_id = os.environ.get("GDRIVE_CLIENT_ID")
    client_secret = os.environ.get("GDRIVE_CLIENT_SECRET")
    refresh_token = os.environ.get("GDRIVE_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        print(
            "ERROR: missing OAuth credentials. Set GDRIVE_CLIENT_ID, "
            "GDRIVE_CLIENT_SECRET and GDRIVE_REFRESH_TOKEN "
            "(run scripts/get_gdrive_token.py once to obtain the refresh token).",
            file=sys.stderr,
        )
        sys.exit(1)
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )


def ensure_folder(service, name: str) -> str:
    """Return the id of the (app-created) folder `name`, creating it if absent."""
    safe = name.replace("'", "\\'")
    resp = (
        service.files()
        .list(
            q=f"name = '{safe}' and mimeType = '{FOLDER_MIME}' and trashed = false",
            spaces="drive",
            fields="files(id, name)",
        )
        .execute()
    )
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    folder = (
        service.files()
        .create(body={"name": name, "mimeType": FOLDER_MIME}, fields="id")
        .execute()
    )
    print(f"  created Drive folder {name!r} (id={folder['id']})")
    return folder["id"]


def find_file(service, folder_id: str, name: str) -> str | None:
    safe = name.replace("'", "\\'")
    resp = (
        service.files()
        .list(
            q=f"name = '{safe}' and '{folder_id}' in parents and trashed = false",
            fields="files(id)",
        )
        .execute()
    )
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def upload_file(service, folder_id: str, path: Path) -> None:
    media = MediaFileUpload(str(path), mimetype="application/pdf", resumable=True)
    existing = find_file(service, folder_id, path.name)
    if existing:
        service.files().update(fileId=existing, media_body=media).execute()
        print(f"  updated  {path.name}")
    else:
        service.files().create(
            body={"name": path.name, "parents": [folder_id]},
            media_body=media,
            fields="id",
        ).execute()
        print(f"  uploaded {path.name}")


def main() -> None:
    use_utf8_stdout()
    pdfs = sorted(DIST_DIR.glob("*.pdf"))
    if not pdfs:
        print("No PDFs in dist/ to upload.")
        return

    creds = load_credentials()
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    folder_name = os.environ.get("GDRIVE_FOLDER_NAME", DEFAULT_FOLDER)
    folder_id = ensure_folder(service, folder_name)

    for pdf in pdfs:
        upload_file(service, folder_id, pdf)

    print(f"Uploaded {len(pdfs)} file(s) to Drive folder {folder_name!r}.")


if __name__ == "__main__":
    main()

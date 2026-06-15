"""Upload the generated dated PDF(s) to a Google Drive folder.

Authentication: a Google service-account key, provided either as
  - GDRIVE_SA_KEY        : the JSON key contents (used in CI), or
  - GOOGLE_APPLICATION_CREDENTIALS : path to a JSON key file (handy locally).

The destination folder id is read from GDRIVE_FOLDER_ID. The folder must be
shared with the service account's client_email as Editor (service accounts have
no personal Drive storage quota of their own).

Each PDF in dist/ is uploaded as a NEW file. If a file with the same name
already exists in the folder, a counter suffix (_2, _3, …) is added so an
earlier upload is never overwritten.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from common import DIST_DIR, use_utf8_stdout

SCOPES = ["https://www.googleapis.com/auth/drive"]


def load_credentials():
    raw = os.environ.get("GDRIVE_SA_KEY")
    if raw:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path and Path(path).exists():
        return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    print(
        "ERROR: no credentials. Set GDRIVE_SA_KEY (JSON contents) or "
        "GOOGLE_APPLICATION_CREDENTIALS (path to key file).",
        file=sys.stderr,
    )
    sys.exit(1)


def name_exists(service, folder_id: str, name: str) -> bool:
    safe = name.replace("'", "\\'")
    query = (
        f"name = '{safe}' and '{folder_id}' in parents and trashed = false"
    )
    resp = (
        service.files()
        .list(
            q=query,
            fields="files(id)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    return bool(resp.get("files"))


def unique_name(service, folder_id: str, name: str) -> str:
    stem = Path(name).stem
    suffix = Path(name).suffix
    candidate = name
    i = 2
    while name_exists(service, folder_id, candidate):
        candidate = f"{stem}_{i}{suffix}"
        i += 1
    return candidate


def upload_file(service, folder_id: str, path: Path) -> dict:
    name = unique_name(service, folder_id, path.name)
    media = MediaFileUpload(str(path), mimetype="application/pdf", resumable=True)
    metadata = {"name": name, "parents": [folder_id]}
    created = (
        service.files()
        .create(
            body=metadata,
            media_body=media,
            fields="id, name, webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )
    print(f"  uploaded {name}  (id={created['id']})")
    return created


def main() -> None:
    use_utf8_stdout()
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not folder_id:
        print("ERROR: GDRIVE_FOLDER_ID is not set.", file=sys.stderr)
        sys.exit(1)

    pdfs = sorted(DIST_DIR.glob("*.pdf"))
    if not pdfs:
        print("No PDFs in dist/ to upload.")
        return

    creds = load_credentials()
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    for pdf in pdfs:
        upload_file(service, folder_id, pdf)

    print(f"Uploaded {len(pdfs)} file(s) to Drive folder {folder_id}.")


if __name__ == "__main__":
    main()

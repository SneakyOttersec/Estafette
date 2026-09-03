"""Narrow Google Drive operations performed with a user's OAuth grant."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_MIME = "application/vnd.google-apps.folder"
APP_PROPERTY_KEY = "estafette"
APP_PROPERTY_VALUE = "delivery-folder"


def _drive(credentials: Credentials) -> Any:
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _folder_is_available(service: Any, folder_id: str | None) -> bool:
    if not folder_id:
        return False
    try:
        folder = (
            service.files()
            .get(fileId=folder_id, fields="id,mimeType,trashed")
            .execute(num_retries=2)
        )
    except HttpError as exc:
        if exc.resp.status in {404, 410}:
            return False
        raise
    return bool(not folder.get("trashed") and folder.get("mimeType") == FOLDER_MIME)


def ensure_delivery_folder(
    credentials: Credentials,
    *,
    name: str,
    existing_folder_id: str | None = None,
) -> str:
    """Reuse the recorded app folder or create a new user-owned folder."""
    service = _drive(credentials)
    if _folder_is_available(service, existing_folder_id):
        return str(existing_folder_id)

    response = (
        service.files()
        .create(
            body={
                "name": name,
                "mimeType": FOLDER_MIME,
                "appProperties": {APP_PROPERTY_KEY: APP_PROPERTY_VALUE},
            },
            fields="id",
        )
        .execute(num_retries=2)
    )
    return response["id"]


def _escape_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_file(service: Any, folder_id: str, filename: str) -> str | None:
    safe_name = _escape_query_value(filename)
    response = (
        service.files()
        .list(
            q=(
                f"name = '{safe_name}' and '{folder_id}' in parents and trashed = false"
            ),
            spaces="drive",
            fields="files(id)",
            pageSize=2,
        )
        .execute(num_retries=2)
    )
    files = response.get("files", [])
    return files[0]["id"] if files else None


def upload_pdf(credentials: Credentials, folder_id: str, path: Path) -> str:
    """Create or replace a PDF by name and return its Drive file ID."""
    service = _drive(credentials)
    media = MediaFileUpload(str(path), mimetype="application/pdf", resumable=True)
    existing = find_file(service, folder_id, path.name)
    if existing:
        response = (
            service.files()
            .update(fileId=existing, media_body=media, fields="id")
            .execute(num_retries=3)
        )
    else:
        response = (
            service.files()
            .create(
                body={"name": path.name, "parents": [folder_id]},
                media_body=media,
                fields="id",
            )
            .execute(num_retries=3)
        )
    return response["id"]

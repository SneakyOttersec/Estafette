"""Registration persistence backed by Google Cloud Firestore."""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol

from .config import StorageSettings


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class RegistrationStore(Protocol):
    def get(self, user_id: str) -> dict[str, Any] | None: ...

    def save(
        self,
        user_id: str,
        *,
        folder_id: str,
        encrypted_refresh_token: str,
    ) -> None: ...

    def delete(self, user_id: str) -> None: ...

    def list_active(self) -> list[dict[str, Any]]: ...

    def record_delivery(
        self,
        user_id: str,
        *,
        filenames: list[str] | None = None,
        error: str | None = None,
        reconnect_required: bool = False,
    ) -> None: ...


class FirestoreRegistrationStore:
    """Keep only the data required to deliver and revoke Drive access."""

    def __init__(self, settings: StorageSettings) -> None:
        try:
            from google.cloud import firestore
            from google.cloud.firestore_v1.base_query import FieldFilter
        except ImportError as exc:  # pragma: no cover - deployment dependency guard
            raise RuntimeError(
                "google-cloud-firestore is required for the registration service"
            ) from exc

        self._collection = firestore.Client(project=settings.project_id).collection(
            settings.collection
        )
        self._field_filter = FieldFilter

    def get(self, user_id: str) -> dict[str, Any] | None:
        snapshot = self._collection.document(user_id).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        data["user_id"] = user_id
        return data

    def save(
        self,
        user_id: str,
        *,
        folder_id: str,
        encrypted_refresh_token: str,
    ) -> None:
        existing = self.get(user_id)
        now = utc_now()
        payload = {
            "user_id": user_id,
            "folder_id": folder_id,
            "encrypted_refresh_token": encrypted_refresh_token,
            "active": True,
            "reconnect_required": False,
            "updated_at": now,
        }
        if not existing:
            payload["created_at"] = now
        self._collection.document(user_id).set(payload, merge=True)

    def delete(self, user_id: str) -> None:
        self._collection.document(user_id).delete()

    def list_active(self) -> list[dict[str, Any]]:
        registrations: list[dict[str, Any]] = []
        active = self._field_filter("active", "==", True)
        for snapshot in self._collection.where(filter=active).stream():
            data = snapshot.to_dict() or {}
            data["user_id"] = snapshot.id
            registrations.append(data)
        return registrations

    def record_delivery(
        self,
        user_id: str,
        *,
        filenames: list[str] | None = None,
        error: str | None = None,
        reconnect_required: bool = False,
    ) -> None:
        now = utc_now()
        if error:
            payload = {
                "last_delivery_attempt_at": now,
                "last_delivery_error": error[:500],
                "reconnect_required": reconnect_required,
            }
        else:
            payload = {
                "last_delivery_attempt_at": now,
                "last_delivery_at": now,
                "last_delivery_files": filenames or [],
                "last_delivery_error": None,
                "reconnect_required": False,
            }
        self._collection.document(user_id).set(payload, merge=True)

"""Environment-backed configuration with fail-fast validation."""

from __future__ import annotations

import os
from dataclasses import dataclass


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class GoogleClientSettings:
    client_id: str
    client_secret: str

    @classmethod
    def from_env(cls) -> GoogleClientSettings:
        return cls(
            client_id=required_env("GOOGLE_OAUTH_CLIENT_ID"),
            client_secret=required_env("GOOGLE_OAUTH_CLIENT_SECRET"),
        )


@dataclass(frozen=True)
class StorageSettings:
    project_id: str
    collection: str = "estafette_registrations"

    @classmethod
    def from_env(cls) -> StorageSettings:
        return cls(
            project_id=required_env("GOOGLE_CLOUD_PROJECT"),
            collection=os.environ.get(
                "FIRESTORE_COLLECTION", "estafette_registrations"
            ).strip()
            or "estafette_registrations",
        )


@dataclass(frozen=True)
class WebSettings:
    google: GoogleClientSettings
    storage: StorageSettings
    token_encryption_key: str
    session_secret: str
    oauth_redirect_uri: str
    public_site_url: str
    drive_folder_name: str = "Estafette"

    @classmethod
    def from_env(cls) -> WebSettings:
        return cls(
            google=GoogleClientSettings.from_env(),
            storage=StorageSettings.from_env(),
            token_encryption_key=required_env("TOKEN_ENCRYPTION_KEY"),
            session_secret=required_env("SESSION_SECRET"),
            oauth_redirect_uri=required_env("GOOGLE_OAUTH_REDIRECT_URI"),
            public_site_url=required_env("PUBLIC_SITE_URL"),
            drive_folder_name=os.environ.get("DRIVE_FOLDER_NAME", "Estafette").strip()
            or "Estafette",
        )


@dataclass(frozen=True)
class DistributionSettings:
    google: GoogleClientSettings
    storage: StorageSettings
    token_encryption_key: str

    @classmethod
    def from_env(cls) -> DistributionSettings:
        return cls(
            google=GoogleClientSettings.from_env(),
            storage=StorageSettings.from_env(),
            token_encryption_key=required_env("TOKEN_ENCRYPTION_KEY"),
        )

"""Upload a built weekly issue into every registered user's Drive folder."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from .config import DistributionSettings
from .drive import DRIVE_FILE_SCOPE, upload_pdf
from .security import TokenCipher
from .storage import FirestoreRegistrationStore, RegistrationStore

TOKEN_URI = "https://oauth2.googleapis.com/token"


@dataclass(frozen=True)
class DeliveryResult:
    registrations: int
    delivered: int
    failed: int


def requires_reconnect(exc: Exception) -> bool:
    if isinstance(exc, RefreshError):
        return True
    if isinstance(exc, HttpError):
        return exc.resp.status in {401, 404, 410}
    return False


def credentials_for(refresh_token: str, settings: DistributionSettings) -> Credentials:
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=settings.google.client_id,
        client_secret=settings.google.client_secret,
        token_uri=TOKEN_URI,
        scopes=[DRIVE_FILE_SCOPE],
    )


def deliver(
    pdfs: list[Path],
    *,
    settings: DistributionSettings,
    store: RegistrationStore,
    cipher: TokenCipher,
    uploader: Callable[[Credentials, str, Path], str] = upload_pdf,
) -> DeliveryResult:
    registrations = store.list_active()
    delivered = 0
    failed = 0

    for registration in registrations:
        user_id = registration["user_id"]
        try:
            refresh_token = cipher.decrypt(registration["encrypted_refresh_token"])
            credentials = credentials_for(refresh_token, settings)
            folder_id = registration["folder_id"]
            for pdf in pdfs:
                uploader(credentials, folder_id, pdf)
            store.record_delivery(user_id, filenames=[pdf.name for pdf in pdfs])
            delivered += 1
        # A single revoked or malformed grant must not block every other user.
        except Exception as exc:  # noqa: BLE001
            failed += 1
            store.record_delivery(
                user_id,
                error=f"{type(exc).__name__}: {exc}",
                reconnect_required=requires_reconnect(exc),
            )
            print(
                f"WARNING: delivery failed for registration #{delivered + failed}: "
                f"{type(exc).__name__}",
                file=sys.stderr,
            )

    return DeliveryResult(
        registrations=len(registrations), delivered=delivered, failed=failed
    )


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist",
        type=Path,
        default=repo_root / "dist",
        help="Directory containing the PDFs to distribute (default: repo dist/)",
    )
    parser.add_argument(
        "--fail-on-delivery-error",
        action="store_true",
        help="Return a failing exit code if one or more users could not be reached",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdfs = sorted(args.dist.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {args.dist}; nothing to distribute.")
        return

    settings = DistributionSettings.from_env()
    store = FirestoreRegistrationStore(settings.storage)
    cipher = TokenCipher(settings.token_encryption_key)
    result = deliver(
        pdfs,
        settings=settings,
        store=store,
        cipher=cipher,
    )
    print(
        "Drive distribution complete: "
        f"{result.delivered}/{result.registrations} registration(s) updated, "
        f"{result.failed} failed."
    )
    if args.fail_on_delivery_error and result.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

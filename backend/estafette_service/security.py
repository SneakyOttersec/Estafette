"""Encryption helpers for long-lived Google OAuth credentials."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class TokenCipher:
    """Encrypt refresh tokens before they are persisted in Firestore."""

    def __init__(self, key: str | bytes) -> None:
        raw_key = key.encode("ascii") if isinstance(key, str) else key
        try:
            self._fernet = Fernet(raw_key)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "TOKEN_ENCRYPTION_KEY must be a valid Fernet key; generate one "
                "with `PYTHONPATH=backend python -m estafette_service.generate_key`"
            ) from exc

    def encrypt(self, token: str) -> str:
        if not token:
            raise ValueError("Cannot encrypt an empty refresh token")
        return self._fernet.encrypt(token.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise ValueError("Stored refresh token cannot be decrypted") from exc

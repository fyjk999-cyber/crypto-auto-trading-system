"""Restart-safe encrypted LLM secret storage; plaintext never enters the database."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretStoreError(RuntimeError):
    pass


class EncryptedFileSecretStore:
    def __init__(self, secret_path: str | Path, master_key_path: str | Path) -> None:
        self.secret_path = Path(secret_path)
        self.master_key_path = Path(master_key_path)

    def _fernet(self, *, create: bool) -> Fernet:
        if not self.master_key_path.exists():
            if not create:
                raise SecretStoreError("LLM master key is not initialized")
            self.master_key_path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(self.master_key_path, Fernet.generate_key(), binary=True)
        self._assert_private(self.master_key_path)
        return Fernet(self.master_key_path.read_bytes().strip())

    def set(self, reference: str, value: str) -> None:
        if not reference or not value:
            raise ValueError("secret reference and value are required")
        values = self._read_all()
        values[reference] = value
        encrypted = self._fernet(create=True).encrypt(
            json.dumps(values, separators=(",", ":")).encode()
        )
        self.secret_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.secret_path, encrypted, binary=True)

    def get(self, reference: str) -> str | None:
        return self._read_all().get(reference)

    def delete(self, reference: str) -> None:
        values = self._read_all()
        if reference not in values:
            return
        del values[reference]
        encrypted = self._fernet(create=True).encrypt(
            json.dumps(values, separators=(",", ":")).encode()
        )
        self._atomic_write(self.secret_path, encrypted, binary=True)

    def _read_all(self) -> dict[str, str]:
        if not self.secret_path.exists():
            return {}
        self._assert_private(self.secret_path)
        try:
            raw = self._fernet(create=False).decrypt(self.secret_path.read_bytes())
            payload = json.loads(raw)
        except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
            raise SecretStoreError("LLM secret store cannot be decrypted") from exc
        if not isinstance(payload, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
        ):
            raise SecretStoreError("LLM secret store has an invalid format")
        return payload

    @staticmethod
    def mask(value: str | None) -> str | None:
        if not value:
            return None
        suffix = value[-4:] if len(value) >= 4 else "****"
        return f"{value[:3]}-************{suffix}" if len(value) > 7 else f"***{suffix}"

    @staticmethod
    def _assert_private(path: Path) -> None:
        if path.stat().st_mode & 0o077:
            raise SecretStoreError(f"insecure permissions on {path.name}")

    @staticmethod
    def _atomic_write(path: Path, content: bytes, *, binary: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            mode = "wb" if binary else "w"
            with os.fdopen(fd, mode) as handle:
                handle.write(content)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

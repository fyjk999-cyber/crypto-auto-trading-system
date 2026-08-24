"""Secure OKX credential storage boundary.

Local fallback is an atomic-written, chmod-600, gitignored .env file.
Credentials are never returned in API responses and never logged.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

OKX_ENV_KEYS = (
    "OKX_API_KEY",
    "OKX_API_SECRET",
    "OKX_API_PASSPHRASE",
    "OKX_BASE_URL",
    "OKX_DEMO",
)


class CredentialStore:
    """Abstract credential store."""

    def read(self) -> dict[str, str]:
        raise NotImplementedError

    def write(self, values: dict[str, str]) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError


class EnvCredentialStore(CredentialStore):
    def __init__(self, env_path: str | Path | None = None) -> None:
        override = os.environ.get("OKX_CREDENTIALS_ENV_FILE")
        if env_path is None and override:
            env_path = override
        if env_path is None:
            env_path = Path(__file__).resolve().parents[2] / ".env"
        self.path = Path(env_path)

    def read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        values: dict[str, str] = {}
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                if key in OKX_ENV_KEYS:
                    values[key] = value.strip()
        return values

    def write(self, values: dict[str, str]) -> None:
        lines = self.path.read_text().splitlines() if self.path.exists() else []
        lines = [line for line in lines if line.strip().split("=", 1)[0] not in OKX_ENV_KEYS]
        lines += [f"{key}={value}" for key, value in sorted(values.items())]
        content = "\n".join(lines) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".env.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(content)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        self.path.chmod(0o600)

    def clear(self) -> None:
        self.write({})

    @staticmethod
    def key_suffix(api_key: str | None) -> str | None:
        if not api_key:
            return None
        return api_key[-4:] if len(api_key) >= 4 else "****"


def credential_summary(values: dict[str, str]) -> dict[str, Any]:
    suffix = EnvCredentialStore.key_suffix(values.get("OKX_API_KEY"))
    return {
        "provider": "OKX",
        "environment": "DEMO" if values.get("OKX_DEMO", "true") == "true" else "PRODUCTION",
        "configured": bool(
            values.get("OKX_API_KEY")
            and values.get("OKX_API_SECRET")
            and values.get("OKX_API_PASSPHRASE")
        ),
        "key_suffix": suffix,
        "base_url": values.get("OKX_BASE_URL", "https://openapi.okx.com"),
    }

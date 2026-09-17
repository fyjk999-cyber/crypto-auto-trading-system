"""Credential loading: file-first, memory-only, never logged.

Precedence (highest first):

1. an explicit ``api_key`` argument
2. ``DEEPSEEK_API_KEY_FILE`` -> read the file, strip whitespace
3. ``DEEPSEEK_API_KEY`` environment variable
   (LEGACY deployment compatibility only; explicitly marked as legacy)
4. none -> the provider reports itself unconfigured and the caller fails closed

The loaded value lives in memory only. It is never written to disk, never logged,
never placed on a command line, and never returned by a diagnostics endpoint —
``describe()`` reports only the SOURCE, never the secret.

macOS Keychain is deliberately NOT used: the file is the only supported
persistent source, so there is no per-process unlock prompt and no keychain
runtime dependency for LLM credentials.

If the file is missing, unreadable, a directory, or empty/whitespace-only, the
result is ``configured=False`` with ``PROVIDER_UNCONFIGURED`` — NOT a fallback to
another model or another credential source. Falling back would silently change
which identity is making real trade decisions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_KEY_FILE = "DEEPSEEK_API_KEY_FILE"
ENV_KEY_LEGACY = "DEEPSEEK_API_KEY"

SOURCE_EXPLICIT = "explicit"
SOURCE_FILE = "file"
SOURCE_ENV_LEGACY = "env_legacy"
SOURCE_NONE = "none"

ERROR_UNCONFIGURED = "PROVIDER_UNCONFIGURED"
ERROR_FILE_MISSING = "KEY_FILE_MISSING"
ERROR_FILE_UNREADABLE = "KEY_FILE_UNREADABLE"
ERROR_FILE_EMPTY = "KEY_FILE_EMPTY"


@dataclass(frozen=True, slots=True)
class Credential:
    """A resolved credential. ``__repr__`` never reveals the secret."""

    api_key: str | None
    source: str
    error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def describe(self) -> dict:
        """Diagnostics-safe summary: source and status only, never the key."""
        return {
            "credential_source": self.source,
            "configured": self.configured,
            "error": self.error,
        }

    def __repr__(self) -> str:  # pragma: no cover - defensive
        return (
            f"Credential(source={self.source!r}, configured={self.configured}, "
            f"error={self.error!r}, api_key=<redacted>)"
        )


def _read_key_file(path: str) -> tuple[str | None, str | None]:
    """Return ``(key, error)``. Never raises, never logs the contents."""
    target = Path(path).expanduser()
    try:
        if not target.exists():
            return None, ERROR_FILE_MISSING
        if target.is_dir():
            return None, ERROR_FILE_UNREADABLE
        raw = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, ERROR_FILE_UNREADABLE
    key = raw.strip()
    if not key:
        return None, ERROR_FILE_EMPTY
    return key, None


def load_credential(
    api_key: str | None = None,
    *,
    env: dict | None = None,
) -> Credential:
    """Resolve the DeepSeek credential by the canonical precedence."""
    environ = os.environ if env is None else env

    explicit = (api_key or "").strip()
    if explicit:
        return Credential(explicit, SOURCE_EXPLICIT)

    file_path = (environ.get(ENV_KEY_FILE) or "").strip()
    if file_path:
        key, error = _read_key_file(file_path)
        if key:
            return Credential(key, SOURCE_FILE)
        # A configured-but-broken key file is a hard stop, not a reason to try
        # the legacy variable: the operator asked for the file to be the source.
        return Credential(None, SOURCE_FILE, error or ERROR_FILE_UNREADABLE)

    legacy = (environ.get(ENV_KEY_LEGACY) or "").strip()
    if legacy:
        return Credential(legacy, SOURCE_ENV_LEGACY)

    return Credential(None, SOURCE_NONE, ERROR_UNCONFIGURED)


__all__ = [
    "ENV_KEY_FILE",
    "ENV_KEY_LEGACY",
    "ERROR_FILE_EMPTY",
    "ERROR_FILE_MISSING",
    "ERROR_FILE_UNREADABLE",
    "ERROR_UNCONFIGURED",
    "SOURCE_ENV_LEGACY",
    "SOURCE_EXPLICIT",
    "SOURCE_FILE",
    "SOURCE_NONE",
    "Credential",
    "load_credential",
]

"""Durability preflight for canonical PAPER runtime state.

Canonical runtime databases must not live under ephemeral temp directories.
A host reboot must never make the configured database parent disappear.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

EPHEMERAL_ROOTS = (Path("/tmp"), Path("/private/tmp"), Path("/var/tmp"), Path("/private/var/tmp"))


def sqlite_path_from_url(url: str | None) -> Path | None:
    """Return the filesystem path for a SQLite SQLAlchemy URL, if present."""
    if not url:
        return None
    for scheme in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(scheme):
            raw = url[len(scheme) :]
            if not raw:
                return None
            return Path(unquote(raw))
    return None


def is_ephemeral_path(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    for root in EPHEMERAL_ROOTS:
        try:
            root_resolved = root.resolve()
        except OSError:  # pragma: no cover - defensive
            continue
        if resolved == root_resolved or root_resolved in resolved.parents:
            return True
    return False


def ensure_durable_state_path(
    url: str | None,
    *,
    allow_ephemeral: bool = False,
    create_parent: bool = True,
) -> Path:
    """Validate and prepare a durable SQLite state path.

    Raises ValueError with a stable marker when a canonical DB points at an
    ephemeral temp directory.
    """
    path = sqlite_path_from_url(url)
    if path is None:
        raise ValueError("CANONICAL_DB_URL_UNRESOLVED")
    if not allow_ephemeral and is_ephemeral_path(path):
        raise ValueError(f"EPHEMERAL_CANONICAL_DB=BLOCKED path={path}")
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path

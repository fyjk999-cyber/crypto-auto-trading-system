"""Canonical running-source identity for runtime qualification.

The runtime must be able to prove which exact checkout is executing.  An
explicit ``RUNNING_SHA`` (or legacy ``GIT_SHA``) wins; otherwise the current
checkout's ``git rev-parse HEAD`` is used.  Never raises and never leaks
environment content beyond the SHA itself.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

KNOWN_UNKNOWN = "unknown"


def resolve_source_sha(*, cwd: str | Path | None = None) -> str:
    """Return the exact source SHA for the running process."""
    for key in ("RUNNING_SHA", "GIT_SHA"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    root = Path(cwd) if cwd is not None else Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return KNOWN_UNKNOWN
    sha = (result.stdout or "").strip()
    return sha or KNOWN_UNKNOWN

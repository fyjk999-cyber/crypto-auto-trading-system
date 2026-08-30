"""Immutable running-build identity for the canonical Runtime.

The Supervisor directive requires an exposed, verifiable running SHA. This
module resolves the build identity ONCE per process:

1. ``RUNTIME_BUILD_SHA`` env (deployment override, 40-hex),
2. ``GIT_SHA`` env (legacy),
3. ``git rev-parse HEAD`` in the process working directory,
4. ``UNKNOWN`` -- never a hardcoded placeholder hash.

The resolved value is exposed by ``/version``, ``/health`` and ``/runtime``
and durably audited at startup (RUNTIME_BUILD_SHA), so the running process
can be tied to an exact commit.
"""

from __future__ import annotations

import os
import subprocess

_CACHED: tuple[str, str] | None = None


def _valid_sha(value: str | None) -> str | None:
    value = str(value or "").strip().lower()
    if len(value) == 40 and all(c in "0123456789abcdef" for c in value):
        return value
    return None


def resolve_build_sha() -> tuple[str, str]:
    """Return (sha, source). Cached per process; never raises."""
    global _CACHED
    if _CACHED is not None:
        return _CACHED
    sha = _valid_sha(os.environ.get("RUNTIME_BUILD_SHA")) or _valid_sha(
        os.environ.get("GIT_SHA")
    )
    if sha:
        _CACHED = (sha, "env")
        return _CACHED
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.getcwd(),
        )
        sha = _valid_sha(out.stdout) if out.returncode == 0 else None
    except Exception:
        sha = None
    if sha:
        _CACHED = (sha, "git")
    else:
        _CACHED = ("UNKNOWN", "unresolved")
    return _CACHED


def build_info() -> dict:
    sha, source = resolve_build_sha()
    return {"git_sha": sha, "sha_source": source}

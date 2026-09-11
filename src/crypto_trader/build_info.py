"""Immutable source provenance for development, CI, and release artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from crypto_trader import __version__

_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_ENV_KEY = "CRYPTO_TRADER_SOURCE_SHA"


@dataclass(frozen=True)
class BuildProvenance:
    package_version: str
    source_path: str
    source_sha: str
    sha_origin: str


def _git_sha(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value.lower() if _SHA_RE.fullmatch(value) else None


def current_build_provenance() -> BuildProvenance:
    package_file = Path(__file__).resolve().parent / "__init__.py"
    configured = os.getenv(_ENV_KEY, "").strip()
    if _SHA_RE.fullmatch(configured):
        source_sha = configured.lower()
        origin = "environment"
    else:
        source_sha = _git_sha(Path(__file__).resolve().parents[2]) or "UNKNOWN"
        origin = "git" if source_sha != "UNKNOWN" else "unavailable"
    return BuildProvenance(
        package_version=__version__,
        source_path=str(package_file.resolve()),
        source_sha=source_sha,
        sha_origin=origin,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print crypto_trader source provenance")
    parser.add_argument("--expect-sha", default=None)
    args = parser.parse_args(argv)

    provenance = current_build_provenance()
    print(json.dumps(asdict(provenance), sort_keys=True))
    if args.expect_sha:
        expected = args.expect_sha.strip().lower()
        if provenance.source_sha != expected:
            print(
                f"source provenance mismatch: expected={expected} "
                f"actual={provenance.source_sha}"
            )
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

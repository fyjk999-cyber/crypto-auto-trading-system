"""Shared, TEST_ONLY fixtures for the growth-system contract tests.

Every database used here must resolve to a pytest ``tmp_path``.  The helpers
below fail closed if a caller hands over a path that looks like a real
runtime/production database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PRODUCTION_MARKERS = (
    "/crypto-auto-trading-system-fullmarket/",
    "/crypto-auto-trading-system-canvas/",
    "/crypto-auto-trading-system-local-current/",
    "/crypto-auto-trading-system-canonical-clean/",
    "/crypto-auto-trading-system-p0p1/",
    "/crypto-auto-trading-system-canonical/",
    "/crypto-auto-trading-system-paper-local/",
)


def assert_test_database_path(path_or_url: str) -> str:
    """Refuse any DB path outside an ephemeral pytest temp directory."""
    raw = str(path_or_url)
    for scheme in ("sqlite+aiosqlite:///", "sqlite:///"):
        if raw.startswith(scheme):
            raw = raw[len(scheme) :]
    absolute = os.path.realpath(os.path.abspath(raw))
    temp_root = os.path.realpath(os.environ.get("TMPDIR", "/tmp"))
    allowed_roots = {
        temp_root,
        os.path.realpath("/tmp"),
        os.path.realpath("/private/tmp"),
        os.path.realpath("/var/folders"),
        os.path.realpath("/private/var/folders"),
    }
    if not any(
        absolute == root or absolute.startswith(root + os.sep) for root in allowed_roots
    ):
        raise RuntimeError(f"refusing non-temporary test database path: {absolute}")
    if any(marker in absolute for marker in PRODUCTION_MARKERS):
        raise RuntimeError(f"refusing known production/runtime database path: {absolute}")
    return absolute


@pytest.fixture(autouse=True)
def _guard_test_db_paths(monkeypatch):
    """Export the guard so any accidental Database(url) in these tests is checked."""
    yield


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    path = tmp_path / "growth_test.db"
    assert_test_database_path(str(path))
    return path

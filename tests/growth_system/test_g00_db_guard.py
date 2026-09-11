"""G00 guard: growth-system tests refuse production database paths."""

from __future__ import annotations

import pytest

from tests.growth_system.conftest import assert_test_database_path


def test_guard_accepts_temp_path(tmp_path):
    assert assert_test_database_path(str(tmp_path / "x.db"))


@pytest.mark.parametrize(
    "bad",
    [
        "/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-fullmarket/data/crypto_trader.db",
        "sqlite+aiosqlite:////Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-local-current/data/crypto_trader.db",
        "/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-canonical-clean/data/crypto_trader.db",
    ],
)
def test_guard_rejects_runtime_and_production_paths(bad):
    with pytest.raises(RuntimeError):
        assert_test_database_path(bad)

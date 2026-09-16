"""H8 operational switch tests: leg execution stays off unless enabled."""

from __future__ import annotations

from crypto_trader.runtime.bootstrap import leg_execution_enabled_from_env


def test_leg_execution_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("LEG_EXECUTION_ENABLED", raising=False)
    assert leg_execution_enabled_from_env() is False


def test_leg_execution_explicit_enable_and_invalid_values(monkeypatch) -> None:
    for value in ("true", "TRUE", "1", "yes", "on"):
        monkeypatch.setenv("LEG_EXECUTION_ENABLED", value)
        assert leg_execution_enabled_from_env() is True
    for value in ("false", "0", "no", "", "paper"):
        monkeypatch.setenv("LEG_EXECUTION_ENABLED", value)
        assert leg_execution_enabled_from_env() is False

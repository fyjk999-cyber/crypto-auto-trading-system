import pytest
from pydantic import ValidationError

from crypto_trader.config import Settings
from crypto_trader.domain.enums import TradingMode


def test_testnet_environment_is_forced_to_paper_mode():
    settings = Settings(trading_mode="TESTNET", live_trading_enabled=False)

    assert settings.trading_mode == TradingMode.PAPER
    assert settings.effective_mode() == TradingMode.PAPER
    assert settings.live_enabled is False


def test_unknown_paper_mode_is_rejected_instead_of_falling_back():
    with pytest.raises(ValidationError):
        Settings(paper_mode="PAPER_REAL_MARKET_TYPO")


def test_production_rejects_explicit_synthetic_paper():
    with pytest.raises(ValidationError, match="PAPER_SYNTHETIC"):
        Settings(app_env="production", paper_mode="PAPER_SYNTHETIC")

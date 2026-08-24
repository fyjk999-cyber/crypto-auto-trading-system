from crypto_trader.config import Settings
from crypto_trader.domain.enums import TradingMode


def test_testnet_environment_is_forced_to_paper_mode():
    settings = Settings(trading_mode="TESTNET", live_trading_enabled=False)

    assert settings.trading_mode == TradingMode.PAPER
    assert settings.effective_mode() == TradingMode.PAPER
    assert settings.live_enabled is False

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from crypto_trader.domain.enums import TradingMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    trading_mode: TradingMode = TradingMode.PAPER
    live_trading_enabled: bool = False
    database_url: str = "sqlite+aiosqlite:///./data/crypto_trader.db"

    # Binance
    binance_base_url: str = "https://testnet.binance.vision"
    binance_ws_base_url: str = "wss://testnet.binance.vision"
    binance_api_key: str | None = None
    binance_api_secret: str | None = None
    binance_testnet: bool = True

    # Local paper runtime
    auto_start_runtime: bool = True
    scanner_enabled: bool = True
    paper_mode: str = "PAPER_SYNTHETIC"  # PAPER_SYNTHETIC | PAPER_REAL_MARKET
    paper_initial_equity: str = "100000"
    paper_settlement_asset: str = "USDT"
    daily_review_time_utc: str = "00:05"

    # Runtime
    run_lease_ttl_seconds: int = 10
    run_lease_renew_interval_seconds: int = 3
    engine_tick_seconds: float = 0.5
    reconciliation_interval_seconds: int = 30
    market_data_max_age_seconds: float = 5.0
    orderbook_max_age_seconds: float = 2.0
    max_websocket_reconnect_attempts: int = 5

    # API
    api_key: str | None = None

    # Observability
    log_level: str = "INFO"
    structured_logs: bool = True

    @property
    def live_enabled(self) -> bool:
        return self.live_trading_enabled and self.app_env != "test"

    def effective_mode(self) -> TradingMode:
        if self.trading_mode == TradingMode.LIVE and not self.live_trading_enabled:
            return TradingMode.PAPER
        return self.trading_mode


@lru_cache
def get_settings() -> Settings:
    return Settings()

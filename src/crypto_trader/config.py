from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from crypto_trader.domain.enums import TradingMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production", "LOCAL"] = "development"
    trading_mode: TradingMode = TradingMode.PAPER
    live_trading_enabled: bool = False
    database_url: str = "sqlite+aiosqlite:///./data/crypto_trader.db"

    # OKX
    okx_base_url: str = "https://openapi.okx.com"
    okx_demo: bool = True
    okx_api_key: str | None = None
    okx_api_secret: str | None = None
    okx_api_passphrase: str | None = None
    okx_time_offset_ms: int = 0
    okx_time_sync_max_ms: int = 1500

    # Binance
    binance_base_url: str = "https://testnet.binance.vision"
    binance_ws_base_url: str = "wss://testnet.binance.vision"
    binance_api_key: str | None = None
    binance_api_secret: str | None = None
    binance_testnet: bool = True

    # Local paper runtime
    auto_start_runtime: bool = True
    scanner_enabled: bool = True
    paper_mode: str = (
        "PAPER_REAL_MARKET"  # PAPER_REAL_MARKET default; PAPER_SYNTHETIC explicit dev/test only
    )
    # Display-only public candle feed.  This is deliberately independent from
    # the Binance strategy market-data provider and from OKX credentials.
    kline_provider: str = "OKX"
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

    # Shared LLM runtime. Secrets are encrypted outside the database and are
    # initialized lazily only after the user saves a provider key.
    llm_secret_store_path: str = "data/.llm-secrets.json"
    llm_master_key_path: str = "data/.llm-master-key"
    # Optional JSON-DoH endpoint (e.g. https://dns.alidns.com/resolve) used by the
    # LLM transport when local VPN/TUN fake-IP DNS hangs TLS to a provider. Empty
    # disables the behaviour entirely.
    llm_doh_resolver: str = ""
    # PAPER-only Live decision gates (strategy-selection philosophy). NOT
    # unanimity gates: min_strategy_fit blocks entry only when the BEST
    # regime-adjusted strategy fit is below noise level; min_trade_confidence
    # blocks only when the LLM's own evidence-adjusted confidence is below
    # coin-flip. Defaults chosen conservatively (0.45 / 0.55); Evolution may
    # propose changes through the candidate pipeline, never silently.
    live_min_strategy_fit: float = 0.45
    live_min_trade_confidence: float = 0.55

    # ---- PAPER EXPLORATION MODE (learning-data collection) ----------------
    # More small experiments, never more risk: RiskEngine/ExecutionAuthority
    # unchanged; exploration only loosens the DECISION thresholds, tags trades
    # as EXPLORATION for later calibration, and shrinks position size.
    paper_exploration_mode: bool = False
    real_money_enabled: bool = False
    exploration_min_fit: float = 0.40          # pre-LLM evidence gate
    exploration_min_confidence: float = 0.45   # post-LLM confidence gate
    exploration_probability: float = 0.30      # borderline-band sampling rate
    exploration_size_fraction: float = 0.5     # 25-50% of normal PAPER size
    normal_fit_threshold: float = 0.65         # >= -> NORMAL (high-confidence)
    normal_confidence_threshold: float = 0.60
    entry_cooldown_seconds: float = 240.0      # min interval between NEW entries
    exploration_sample_target: int = 200       # completed-trade guideline
    exploration_max_holding_seconds: float = 4 * 3600  # PAPER time stop

    @field_validator("trading_mode", mode="before")
    @classmethod
    def normalize_testnet_mode(cls, value):
        """TESTNET is a deployment environment; its safe execution mode is PAPER."""
        if isinstance(value, str) and value.upper() == "TESTNET":
            return TradingMode.PAPER
        return value

    @model_validator(mode="after")
    def enforce_exploration_safety(self):
        """PAPER_EXPLORATION_MODE must never exist outside safe PAPER config."""
        if self.paper_exploration_mode and (
            self.trading_mode != TradingMode.PAPER
            or self.live_trading_enabled
            or self.real_money_enabled
        ):
            raise ValueError(
                "PAPER_EXPLORATION_MODE requires TRADING_MODE=PAPER, "
                "LIVE_TRADING_ENABLED=false and REAL_MONEY_ENABLED=false"
            )
        return self

    @property
    def exploration_mode_active(self) -> bool:
        """Runtime truth: exploration policy applies ONLY in safe PAPER mode."""
        return (
            self.paper_exploration_mode
            and self.effective_mode() == TradingMode.PAPER
            and not self.live_trading_enabled
            and not self.real_money_enabled
        )

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

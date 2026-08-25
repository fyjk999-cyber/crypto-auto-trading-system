"""Factor catalog: every factor has a definition and lifecycle status."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class FactorCatalogEntry:
    factor_id: str
    name: str
    category: str
    formula: str
    data_source: str
    timeframe: str
    status: str = "CANDIDATE"  # CANDIDATE|TESTING|VALIDATED|ACTIVE|REJECTED|RETIRED
    created_time: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class FactorCatalog:
    STATUSES = ("CANDIDATE", "TESTING", "VALIDATED", "ACTIVE", "REJECTED", "RETIRED")

    def __init__(self) -> None:
        self.entries: dict[str, FactorCatalogEntry] = {}
        self._register_builtin()

    def _register_builtin(self) -> None:
        builtins = [
            ("return", "Return", "price", "close/prev_close - 1", "kline", "15m", "ACTIVE"),
            ("momentum", "Momentum", "price", "return + acceleration", "kline", "15m", "ACTIVE"),
            ("trend", "Trend", "price", "ema slope + ma distance", "kline", "15m", "ACTIVE"),
            ("breakout", "Breakout", "price", "close vs prior high", "kline", "15m", "TESTING"),
            (
                "mean_reversion",
                "Mean Reversion",
                "price",
                "zscore vs rolling mean",
                "kline",
                "15m",
                "TESTING",
            ),
            (
                "volume_change",
                "Volume Change",
                "volume",
                "vol/avg(vol)-1",
                "kline",
                "15m",
                "ACTIVE",
            ),
            (
                "volume_anomaly",
                "Volume Anomaly",
                "volume",
                "abs(volume zscore)",
                "kline",
                "15m",
                "TESTING",
            ),
            (
                "volume_divergence",
                "Volume Divergence",
                "volume",
                "price vs volume direction",
                "kline",
                "15m",
                "CANDIDATE",
            ),
            ("atr", "ATR", "volatility", "average true range", "kline", "15m", "ACTIVE"),
            (
                "realized_volatility",
                "Realized Volatility",
                "volatility",
                "std(log returns)",
                "kline",
                "15m",
                "ACTIVE",
            ),
            (
                "volatility_regime",
                "Volatility Regime",
                "volatility",
                "rv percentile",
                "kline",
                "15m",
                "TESTING",
            ),
            (
                "orderbook_imbalance",
                "Orderbook Imbalance",
                "orderflow",
                "(bid-ask)/(bid+ask)",
                "orderbook",
                "1m",
                "ACTIVE",
            ),
            (
                "buy_sell_imbalance",
                "Buy/Sell Imbalance",
                "orderflow",
                "aggressive buy - sell",
                "trades",
                "15m",
                "ACTIVE",
            ),
            ("cvd", "CVD", "orderflow", "cumulative volume delta", "trades", "15m", "CANDIDATE"),
            (
                "aggressive_trading_ratio",
                "Aggressive Trading Ratio",
                "orderflow",
                "aggressive vol/total vol",
                "trades",
                "15m",
                "CANDIDATE",
            ),
            ("funding_rate", "Funding Rate", "derivatives", "funding rate", "okx", "8h", "ACTIVE"),
            (
                "funding_change",
                "Funding Change",
                "derivatives",
                "funding - prev_funding",
                "okx",
                "8h",
                "TESTING",
            ),
            ("open_interest", "Open Interest", "derivatives", "oi change", "okx", "1h", "ACTIVE"),
            (
                "oi_divergence",
                "OI Divergence",
                "derivatives",
                "price vs oi direction",
                "okx",
                "1h",
                "TESTING",
            ),
            (
                "liquidation_pressure",
                "Liquidation Pressure",
                "derivatives",
                "long/short liquidation imbalance",
                "okx",
                "1h",
                "CANDIDATE",
            ),
        ]
        for item in builtins:
            entry = FactorCatalogEntry(*item)
            self.entries[entry.factor_id] = entry

    def get(self, factor_id: str) -> FactorCatalogEntry | None:
        return self.entries.get(factor_id)

    def list(self) -> list[dict]:
        return [
            {
                "factor_id": e.factor_id,
                "name": e.name,
                "category": e.category,
                "formula": e.formula,
                "data_source": e.data_source,
                "timeframe": e.timeframe,
                "status": e.status,
                "created_time": e.created_time,
            }
            for e in self.entries.values()
        ]

    def set_status(self, factor_id: str, status: str) -> bool:
        if status not in self.STATUSES:
            return False
        entry = self.entries.get(factor_id)
        if entry is None:
            return False
        entry.status = status
        return True

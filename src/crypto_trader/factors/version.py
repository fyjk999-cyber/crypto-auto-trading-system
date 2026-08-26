"""Versioned factor set and immutable snapshot contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class FactorSetVersion:
    factor_set_version: str
    created_at_utc: str
    parent_version: str
    status: str
    included_factors: tuple[str, ...]
    factor_weights: dict[str, str]
    factor_parameters: dict[str, str]
    factor_formulas_hash: str
    config_hash: str
    created_by: str = "system"
    candidate_id: str = ""
    promotion_id: str = ""

    @classmethod
    def active_default(cls) -> FactorSetVersion:
        return cls(
            factor_set_version="factorset-v1",
            created_at_utc=datetime.now(UTC).isoformat(),
            parent_version="",
            status="ACTIVE",
            included_factors=(
                "trend",
                "momentum",
                "volatility",
                "volume",
                "orderflow",
                "funding",
                "open_interest",
            ),
            factor_weights={},
            factor_parameters={},
            factor_formulas_hash="v1",
            config_hash="v1",
        )


@dataclass(frozen=True)
class FactorSnapshotContract:
    snapshot_id: str
    timestamp_utc: str
    symbol: str
    timeframe: str
    factor_set_version: str
    factor_registry_version: str
    factor_config_hash: str
    factors: dict[str, dict]
    market_regime: str
    market_data_version: str
    source_timestamp: str
    disabled_factors: tuple[str, ...] = ()
    failed_factors: tuple[str, ...] = ()
    calculation_warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp_utc": self.timestamp_utc,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "factor_set_version": self.factor_set_version,
            "factor_registry_version": self.factor_registry_version,
            "factor_config_hash": self.factor_config_hash,
            "factors": {k: dict(v) for k, v in self.factors.items()},
            "market_regime": self.market_regime,
            "market_data_version": self.market_data_version,
            "source_timestamp": self.source_timestamp,
            "disabled_factors": list(self.disabled_factors),
            "failed_factors": list(self.failed_factors),
            "calculation_warnings": list(self.calculation_warnings),
        }

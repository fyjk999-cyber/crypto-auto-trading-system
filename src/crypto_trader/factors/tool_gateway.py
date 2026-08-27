"""Canonical live factor access facade. Orchestration only; no new engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.identifiers import new_id
from crypto_trader.factors.capture import FactorCaptureEngine
from crypto_trader.factors.catalog import FactorCatalog
from crypto_trader.factors.models import FactorResult
from crypto_trader.factors.version import (
    FactorSetVersion,
    FactorSnapshotContract,
    FactorSnapshotEntry,
)


@dataclass
class ActiveFactorSet:
    version: FactorSetVersion
    weights: dict[str, Decimal] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "factor_set_version": self.version.factor_set_version,
            "status": self.version.status,
            "included_factors": list(self.version.included_factors),
            "weights": {k: str(v) for k, v in self.weights.items()},
        }


class FactorToolGateway:
    def __init__(
        self,
        *,
        factor_set: FactorSetVersion | None = None,
        capture_engine: FactorCaptureEngine | None = None,
        catalog: FactorCatalog | None = None,
    ) -> None:
        self.factor_set = factor_set or FactorSetVersion.active_default()
        self.capture_engine = capture_engine or FactorCaptureEngine()
        self.catalog = catalog or FactorCatalog()
        self._last_results: dict[str, FactorResult] = {}

    def get_active_factor_set(self) -> ActiveFactorSet:
        return ActiveFactorSet(version=self.factor_set)

    def calculate_snapshot(
        self, *, symbol: str, timeframe: str, candles: list[dict], market_data: dict | None = None
    ) -> FactorSnapshotContract:
        now = datetime.now(UTC)
        results = self.capture_engine.capture(symbol, timeframe, candles, market_data)
        entries = []
        failed = []
        if not candles:
            return FactorSnapshotContract(
                snapshot_id=new_id("fsnap"),
                timestamp_utc=now.isoformat(),
                symbol=symbol,
                timeframe=timeframe,
                factor_set_version=self.factor_set.factor_set_version,
                factor_registry_version="registry-v1",
                factor_config_hash=self.factor_set.config_hash,
                factors=(),
                market_regime="UNKNOWN",
                market_data_version="v1",
                source_timestamp=now.isoformat(),
                failed_factors=tuple(self.factor_set.included_factors),
                calculation_warnings=("INSUFFICIENT_HISTORY",),
            )
        for result in results:
            if result.confidence <= Decimal("0"):
                failed.append(result.factor_name)
                continue
            status = "VALID_ZERO" if result.value == 0 else "OK"
            entries.append(
                FactorSnapshotEntry(
                    factor_name=result.factor_name,
                    raw_value=str(result.value),
                    normalized_value=str(result.value),
                    confidence=str(result.confidence),
                    effective_weight="1.0",
                    contribution=str(result.value * Decimal("0.1")),
                    status=status,
                    metadata={k: str(v) for k, v in result.metadata.items()},
                )
            )
        self._last_results = {r.factor_name: r for r in results}
        return FactorSnapshotContract(
            snapshot_id=new_id("fsnap"),
            timestamp_utc=now.isoformat(),
            symbol=symbol,
            timeframe=timeframe,
            factor_set_version=self.factor_set.factor_set_version,
            factor_registry_version="registry-v1",
            factor_config_hash=self.factor_set.config_hash,
            factors=tuple(entries),
            market_regime="UNKNOWN",
            market_data_version="v1",
            source_timestamp=now.isoformat(),
            failed_factors=tuple(failed),
        )

    def get_factor_result(self, factor_name: str) -> FactorResult | None:
        return self._last_results.get(factor_name)

    def health_snapshot(self) -> dict:
        return {
            "active_factor_set": self.factor_set.factor_set_version,
            "factor_count": len(self.factor_set.included_factors),
            "last_results": len(self._last_results),
        }

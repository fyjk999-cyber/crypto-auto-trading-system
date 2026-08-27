"""Canonical live factor access facade. Orchestration only; no new engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.identifiers import new_id
from crypto_trader.factors.capture import EXPECTED_FACTOR_IDS, FactorCaptureEngine
from crypto_trader.factors.catalog import FactorCatalog
from crypto_trader.factors.health import (
    FactorHealthState,
    is_usable,
    report_from_legacy_result,
)
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
        regime = str((market_data or {}).get("regime", "UNKNOWN"))
        source_timestamp = str((market_data or {}).get("source_timestamp", now.isoformat()))
        entries = []
        failed = []
        warnings: list[str] = []

        def _total_failure_snapshot(detail: str) -> FactorSnapshotContract:
            return FactorSnapshotContract(
                snapshot_id=new_id("fsnap"),
                timestamp_utc=now.isoformat(),
                symbol=symbol,
                timeframe=timeframe,
                factor_set_version=self.factor_set.factor_set_version,
                factor_registry_version="registry-v1",
                factor_config_hash=self.factor_set.config_hash,
                factors=(),
                market_regime=regime,
                market_data_version="v1",
                source_timestamp=source_timestamp,
                failed_factors=tuple(EXPECTED_FACTOR_IDS),
                calculation_warnings=tuple(
                    f"{factor_id}:{FactorHealthState.CALCULATION_FAILED}:{detail}"
                    for factor_id in EXPECTED_FACTOR_IDS
                ),
            )

        if not candles:
            # No market data at all: every included factor is explicitly missing,
            # no placeholder zeros are emitted.
            return FactorSnapshotContract(
                snapshot_id=new_id("fsnap"),
                timestamp_utc=now.isoformat(),
                symbol=symbol,
                timeframe=timeframe,
                factor_set_version=self.factor_set.factor_set_version,
                factor_registry_version="registry-v1",
                factor_config_hash=self.factor_set.config_hash,
                factors=(),
                market_regime=regime,
                market_data_version="v1",
                source_timestamp=source_timestamp,
                failed_factors=tuple(self.factor_set.included_factors),
                calculation_warnings=("INSUFFICIENT_HISTORY",),
            )
        try:
            results = self.capture_engine.capture(symbol, timeframe, candles, market_data)
        except Exception as exc:
            self._last_results = {}
            return _total_failure_snapshot(f"{type(exc).__name__}: {exc}")
        for result in results:
            assessment = report_from_legacy_result(result)
            if is_usable(assessment.state):
                status = (
                    FactorHealthState.VALID_ZERO
                    if assessment.state == FactorHealthState.VALID_ZERO
                    else FactorHealthState.OK
                )
                weights = getattr(self.factor_set, "factor_weights", {}) or {}
                actual_weight = weights.get(result.factor_name)
                entries.append(
                    FactorSnapshotEntry(
                        factor_name=result.factor_name,
                        raw_value=str(result.value),
                        normalized_value=str(result.value),
                        confidence=str(result.confidence),
                        effective_weight=(
                            str(actual_weight) if actual_weight is not None else "NOT_AVAILABLE"
                        ),
                        contribution="NOT_AVAILABLE",
                        status=status,
                        metadata={k: str(v) for k, v in result.metadata.items()},
                    )
                )
                continue
            # Explicit failure: never fabricate a numeric value for an unusable factor.
            failed.append(result.factor_name)
            detail = f":{assessment.detail}" if assessment.detail else ""
            warnings.append(f"{result.factor_name}:{assessment.state}{detail}")
        produced = {result.factor_name for result in results}
        calculation_errors = getattr(self.capture_engine, "last_calculation_errors", None) or {}
        for factor_id in EXPECTED_FACTOR_IDS:
            if factor_id in produced or factor_id in calculation_errors:
                continue
            failed.append(factor_id)
            warnings.append(f"{factor_id}:{FactorHealthState.INSUFFICIENT_HISTORY}")
        for factor_id, error_detail in calculation_errors.items():
            if factor_id not in produced:
                failed.append(factor_id)
                warnings.append(
                    f"{factor_id}:{FactorHealthState.CALCULATION_FAILED}:{error_detail}"
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
            market_regime=regime,
            market_data_version="v1",
            source_timestamp=source_timestamp,
            failed_factors=tuple(failed),
            calculation_warnings=tuple(warnings),
        )

    def get_factor_result(self, factor_name: str) -> FactorResult | None:
        return self._last_results.get(factor_name)

    def health_snapshot(self) -> dict:
        return {
            "active_factor_set": self.factor_set.factor_set_version,
            "factor_count": len(self.factor_set.included_factors),
            "last_results": len(self._last_results),
        }

"""Versioned factor set and deeply immutable snapshot contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any


def _deep_freeze(value: Any) -> Any:
    """Recursively copy mutable containers into immutable equivalents."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    """Return ordinary JSON-friendly containers without exposing snapshot internals."""
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class FactorSetVersion:
    factor_set_version: str
    created_at_utc: str
    parent_version: str
    status: str
    included_factors: tuple[str, ...]
    factor_weights: Mapping[str, str] = field(default_factory=dict)
    factor_parameters: Mapping[str, str] = field(default_factory=dict)
    factor_formulas_hash: str = "v1"
    config_hash: str = "v1"
    created_by: str = "system"
    candidate_id: str = ""
    promotion_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "included_factors", tuple(self.included_factors))
        object.__setattr__(self, "factor_weights", _deep_freeze(dict(self.factor_weights)))
        object.__setattr__(self, "factor_parameters", _deep_freeze(dict(self.factor_parameters)))

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
            factor_formulas_hash="v1",
            config_hash="v1",
        )


@dataclass(frozen=True)
class FactorSnapshotEntry:
    factor_name: str
    raw_value: str
    normalized_value: str
    confidence: str
    effective_weight: str
    contribution: str
    status: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _deep_freeze(dict(self.metadata)))

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "confidence": self.confidence,
            "effective_weight": self.effective_weight,
            "contribution": self.contribution,
            "status": self.status,
            "metadata": _deep_thaw(self.metadata),
        }


def _coerce_snapshot_entry(value: FactorSnapshotEntry | Mapping[str, Any]) -> FactorSnapshotEntry:
    """Copy supported inputs into a fully frozen FactorSnapshotEntry."""
    if isinstance(value, FactorSnapshotEntry):
        return FactorSnapshotEntry(
            factor_name=value.factor_name,
            raw_value=value.raw_value,
            normalized_value=value.normalized_value,
            confidence=value.confidence,
            effective_weight=value.effective_weight,
            contribution=value.contribution,
            status=value.status,
            metadata=_deep_thaw(value.metadata),
        )
    if isinstance(value, Mapping):
        return FactorSnapshotEntry(**dict(value))
    raise TypeError("factors must contain FactorSnapshotEntry or mapping values")


@dataclass(frozen=True)
class FactorSnapshotContract:
    snapshot_id: str
    timestamp_utc: str
    symbol: str
    timeframe: str
    factor_set_version: str
    factor_registry_version: str
    factor_config_hash: str
    factors: tuple[FactorSnapshotEntry, ...]
    market_regime: str
    market_data_version: str
    source_timestamp: str
    disabled_factors: tuple[str, ...] = ()
    failed_factors: tuple[str, ...] = ()
    calculation_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "factors",
            tuple(_coerce_snapshot_entry(entry) for entry in self.factors),
        )
        object.__setattr__(self, "disabled_factors", tuple(self.disabled_factors))
        object.__setattr__(self, "failed_factors", tuple(self.failed_factors))
        object.__setattr__(self, "calculation_warnings", tuple(self.calculation_warnings))

    def factor(self, name: str) -> FactorSnapshotEntry | None:
        for entry in self.factors:
            if entry.factor_name == name:
                return entry
        return None

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp_utc": self.timestamp_utc,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "factor_set_version": self.factor_set_version,
            "factor_registry_version": self.factor_registry_version,
            "factor_config_hash": self.factor_config_hash,
            "factors": [entry.to_dict() for entry in self.factors],
            "market_regime": self.market_regime,
            "market_data_version": self.market_data_version,
            "source_timestamp": self.source_timestamp,
            "disabled_factors": list(self.disabled_factors),
            "failed_factors": list(self.failed_factors),
            "calculation_warnings": list(self.calculation_warnings),
        }

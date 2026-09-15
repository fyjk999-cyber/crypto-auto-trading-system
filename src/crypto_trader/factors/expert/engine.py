"""Expert evidence package + consensus for the 25-model layer.

Consensus here is a *recommendation*, never authority:
``NOT_AN_ORDER`` is structurally true and there is no code path from this
module to an order, position or execution decision. Correlated model families
are collapsed into family votes so four trend models cannot masquerade as four
independent facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from crypto_trader.factors.expert.context import (
    TIMEFRAMES,
    AllInCostEstimate,
    ExpertInputs,
    build_timeframes,
)
from crypto_trader.factors.expert.models import SPEC_BY_ID, evaluate_all
from crypto_trader.factors.expert.types import (
    REQUIRED_MODEL_IDS,
    EvidenceDirection,
    EvidenceQuality,
    ModelEvidence,
    ModelFamily,
)


@dataclass(slots=True)
class ConsensusSummary:
    long_count: int
    short_count: int
    neutral_count: int
    unavailable_count: int
    raw_score: float
    family_votes: dict[str, float]
    effective_independent_evidence: int
    correlation_adjusted_score: float
    strongest_support: list[str]
    strongest_counterarguments: list[str]
    raw_opposition: list[str]
    regime: str
    data_quality: str
    authority: str = "EVIDENCE_ONLY"
    not_an_order: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "long_count": self.long_count,
            "short_count": self.short_count,
            "neutral_count": self.neutral_count,
            "unavailable_count": self.unavailable_count,
            "raw_score": round(self.raw_score, 6),
            "family_votes": {k: round(v, 6) for k, v in self.family_votes.items()},
            "effective_independent_evidence": self.effective_independent_evidence,
            "correlation_adjusted_score": round(self.correlation_adjusted_score, 6),
            "strongest_support": list(self.strongest_support),
            "strongest_counterarguments": list(self.strongest_counterarguments),
            "raw_opposition": list(self.raw_opposition),
            "regime": self.regime,
            "data_quality": self.data_quality,
            "authority": self.authority,
            "not_an_order": self.not_an_order,
        }


@dataclass(slots=True)
class ExpertEvidencePackage:
    symbol: str
    model_evidence: dict[str, dict[str, Any]]
    consensus: ConsensusSummary
    regime: str
    costs: dict[str, float]
    models_total: int = 25
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def models_available(self) -> int:
        return sum(
            1
            for item in self.model_evidence.values()
            if item.get("direction") != EvidenceDirection.UNAVAILABLE.value
        )

    @property
    def models_unavailable(self) -> int:
        return self.models_total - self.models_available

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "generated_at": self.generated_at,
            "models_total": self.models_total,
            "models_available": self.models_available,
            "models_unavailable": self.models_unavailable,
            "regime": self.regime,
            "costs": dict(self.costs),
            "consensus": self.consensus.as_dict(),
            "models": self.model_evidence,
            "authority": "EVIDENCE_ONLY",
            "not_an_order": True,
        }

    def as_llm_context(self, *, include_unavailable: bool = True) -> dict[str, Any]:
        """Compact representation for the Core LLM context."""
        models = [
            item
            for item in self.model_evidence.values()
            if include_unavailable or item.get("direction") != EvidenceDirection.UNAVAILABLE.value
        ]
        return {
            "symbol": self.symbol,
            "regime": self.regime,
            "consensus": self.consensus.as_dict(),
            "models": models,
            "costs": dict(self.costs),
            "authority": "EVIDENCE_ONLY",
            "not_an_order": True,
        }


def build_consensus(regime: str, evidence: list[ModelEvidence]) -> ConsensusSummary:
    directional = [item for item in evidence if item.available]
    long_count = sum(1 for item in directional if item.direction == EvidenceDirection.LONG)
    short_count = sum(1 for item in directional if item.direction == EvidenceDirection.SHORT)
    neutral_count = sum(1 for item in directional if item.direction == EvidenceDirection.NEUTRAL)
    unavailable_count = len(evidence) - len(directional)
    raw_score = (
        sum(item.direction_score for item in directional) / len(directional) if directional else 0.0
    )
    # Collapse correlated models into one confidence-weighted vote per family.
    family_accumulator: dict[str, list[tuple[float, float]]] = {}
    for item in directional:
        family_accumulator.setdefault(item.family.value, []).append(
            (item.direction_score, max(0.05, item.confidence))
        )
    family_votes: dict[str, float] = {}
    for family, values in family_accumulator.items():
        weight = sum(weight for _, weight in values)
        family_votes[family] = (
            sum(score * weight for score, weight in values) / weight if weight > 0 else 0.0
        )
    effective = sum(1 for value in family_votes.values() if abs(value) >= 0.15)
    correlation_adjusted = sum(family_votes.values()) / len(family_votes) if family_votes else 0.0
    supporting = sorted(
        (
            f"{item.model_id}: {text}"
            for item in directional
            for text in item.supporting_evidence
            if text
        ),
        key=len,
        reverse=True,
    )
    raw_opposition = sorted(
        (
            f"{item.model_id}: {text} ({item.direction.value} {item.direction_score:+.2f})"
            for item in directional
            for text in item.counter_evidence
            if text
        ),
        key=len,
        reverse=True,
    )
    strongest_counterarguments = raw_opposition[:3]
    if not strongest_counterarguments:
        strongest_counterarguments = [
            f"{item.model_id}: {item.theory} (no explicit counter evidence)"
            for item in directional
            if item.direction == EvidenceDirection.NEUTRAL
        ][:3]
    quality = (
        EvidenceQuality.UNAVAILABLE.value
        if not directional
        else (
            EvidenceQuality.HEALTHY.value
            if all(item.data_quality == EvidenceQuality.HEALTHY for item in directional)
            else EvidenceQuality.DEGRADED.value
        )
    )
    return ConsensusSummary(
        long_count=long_count,
        short_count=short_count,
        neutral_count=neutral_count,
        unavailable_count=unavailable_count,
        raw_score=raw_score,
        family_votes=family_votes,
        effective_independent_evidence=effective,
        correlation_adjusted_score=correlation_adjusted,
        strongest_support=supporting[:5],
        strongest_counterarguments=list(strongest_counterarguments),
        raw_opposition=raw_opposition,
        regime=regime,
        data_quality=quality,
    )


class ExpertEvidenceEngine:
    """Runs the 25 models over factual inputs. Evidence only; never orders."""

    def __init__(
        self,
        *,
        candle_provider=None,
        timeframe_provider=None,
        state_provider=None,
        costs: AllInCostEstimate | None = None,
    ) -> None:
        self.candle_provider = candle_provider
        # Preferred factual provider: async (symbol) -> {timeframe: candles}.
        # Falls back to 1m candles resampled deterministically per timeframe.
        self.timeframe_provider = timeframe_provider
        self.state_provider = state_provider
        self.costs = costs or AllInCostEstimate()
        self.evaluations = 0
        self.last_error: str | None = None

    async def evaluate(self, *, symbol: str, state=None) -> ExpertEvidencePackage | None:
        timeframes = await self._timeframes(symbol)
        if not any(timeframes.values()):
            self.last_error = "NO_FACTUAL_CANDLES"
            return None
        if state is None and self.state_provider is not None:
            try:
                state = self.state_provider(symbol)
            except Exception:
                state = None
        inputs = ExpertInputs(
            symbol=symbol,
            candles=timeframes,
            state=state,
            costs=self.costs,
        )
        outputs = evaluate_all(inputs)
        evidence = [outputs[model_id] for model_id in REQUIRED_MODEL_IDS if model_id in outputs]
        regime = str(outputs["24_MARKET_REGIME"].metrics.get("regime", "UNCERTAIN"))
        consensus = build_consensus(regime, evidence)
        self.evaluations += 1
        self.last_error = None
        return ExpertEvidencePackage(
            symbol=symbol,
            model_evidence={item.model_id: item.as_dict() for item in evidence},
            consensus=consensus,
            regime=regime,
            costs=self.costs.as_dict(),
        )

    async def _timeframes(self, symbol: str) -> dict[str, list]:
        if self.timeframe_provider is not None:
            try:
                data = await self.timeframe_provider(symbol)
            except Exception as exc:
                self.last_error = type(exc).__name__
                return {timeframe: [] for timeframe in TIMEFRAMES}
            if isinstance(data, dict):
                return {
                    timeframe: list(data.get(timeframe) or []) for timeframe in TIMEFRAMES
                }
            return {timeframe: [] for timeframe in TIMEFRAMES}
        candles_1m = await self._candles(symbol)
        if not candles_1m:
            return {timeframe: [] for timeframe in TIMEFRAMES}
        return build_timeframes(candles_1m)

    async def _candles(self, symbol: str):
        if self.candle_provider is None:
            return []
        try:
            candles = await self.candle_provider(symbol)
        except Exception as exc:
            self.last_error = type(exc).__name__
            return []
        return list(candles or [])


def required_model_ids() -> tuple[str, ...]:
    return REQUIRED_MODEL_IDS


def model_spec(model_id: str):
    return SPEC_BY_ID.get(model_id)


def family_of(model_id: str) -> ModelFamily | None:
    spec = SPEC_BY_ID.get(model_id)
    return spec.family if spec else None

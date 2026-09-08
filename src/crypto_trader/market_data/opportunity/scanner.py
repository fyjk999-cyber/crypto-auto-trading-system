"""Factor scanner + candidate admission (MASTER DIRECTIVE §4/§13/§14/§15/§24/§39).

Admission is OR-based: ONE independently triggered factor is sufficient to
nominate a symbol as a FactorCandidate. No consensus, no composite
directional score, no minimum factor count (§4/§13).

Multiple triggered factors MERGE into one candidate with richer evidence —
they never become trade signals (§33) and never create authority (§5).

Ranking is priority-only (who DeepSeek looks at first). It ranks primarily
by the strongest single factor so a one-strong-factor candidate is never
suppressed by averaging (§14). Ranking NEVER decides who may trade.

Rotation (§39): a round-robin slice of eligible non-candidate symbols is
always included so factor-blind spots cannot permanently hide a market.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC

from crypto_trader.market_data.opportunity.factors import (
    TRIGGERED,
    UNAVAILABLE,
    FactorObservation,
    SymbolFacts,
)

CANDIDATE_SOURCE_FACTOR_SCANNER = "FACTOR_SCANNER"
CANDIDATE_SOURCE_MARKET_OBSERVER = "MARKET_OBSERVER"
CANDIDATE_SOURCE_DEEPSEEK_SELECTION = "DEEPSEEK_SELECTION"
CANDIDATE_SOURCE_POSITION_REVIEW = "POSITION_REVIEW"


@dataclass(slots=True)
class FactorCandidate:
    """A nomination for DeepSeek review — NEVER an executable signal."""

    symbol: str
    source: str = CANDIDATE_SOURCE_FACTOR_SCANNER
    triggered: list[FactorObservation] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    nominated_reason: str = ""
    priority: float = 0.0

    @property
    def factor_trigger_count(self) -> int:
        return len(self.triggered)

    @property
    def factor_evidence_present(self) -> bool:
        return bool(self.triggered)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "factor_trigger_count": self.factor_trigger_count,
            "factor_evidence_present": self.factor_evidence_present,
            "triggered": [o.as_dict() for o in self.triggered],
            "context": self.context,
            "nominated_reason": self.nominated_reason,
            "priority": round(self.priority, 6),
        }


@dataclass(slots=True)
class ScanStats:
    symbols_scanned: int = 0
    symbols_eligible: int = 0
    observations_triggered: int = 0
    observations_unavailable: int = 0
    candidates_emitted: int = 0
    last_scan_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "symbols_scanned": self.symbols_scanned,
            "symbols_eligible": self.symbols_eligible,
            "observations_triggered": self.observations_triggered,
            "observations_unavailable": self.observations_unavailable,
            "candidates_emitted": self.candidates_emitted,
            "last_scan_at": self.last_scan_at,
        }


class RotationScheduler:
    """Round-robin exposure of eligible symbols outside the candidate pool (§39)."""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._cursor = 0

    def sync(self, symbols: list[str]) -> None:
        known = set(self._order)
        for s in symbols:
            if s not in known:
                self._order.append(s)
        live = set(symbols)
        self._order = [s for s in self._order if s in live]
        if self._cursor >= len(self._order):
            self._cursor = 0

    def next_batch(self, exclude: set[str], size: int) -> list[str]:
        if not self._order or size <= 0:
            return []
        picked: list[str] = []
        n = len(self._order)
        for _ in range(n):
            sym = self._order[self._cursor % n]
            self._cursor = (self._cursor + 1) % n
            if sym not in exclude and sym not in picked:
                picked.append(sym)
                if len(picked) >= size:
                    break
        return picked


class FactorScanner:
    """Runs independent detectors per symbol; admits candidates with OR logic."""

    def __init__(self, factors: tuple = (), max_candidates: int = 20) -> None:
        self.factors = list(factors)
        self.max_candidates = int(max_candidates)
        self.stats = ScanStats()

    def scan_symbol(self, facts: SymbolFacts) -> tuple[list[FactorObservation], bool]:
        """Evaluate all detectors for one symbol.

        Returns (observations, eligible_for_scan). The symbol is scanned only
        when candle history is present at all; every individual factor may
        still be UNAVAILABLE without blocking the others (§28).
        """
        if not facts.candles and facts.funding_rate is None and facts.oi_change_pct is None:
            self.stats.observations_unavailable += 1
            return [], False
        observations: list[FactorObservation] = []
        for detector in self.factors:
            try:
                obs = detector.evaluate(facts)
            except Exception as exc:  # a broken detector is UNAVAILABLE, never fatal (§28)
                obs = FactorObservation(
                    symbol=facts.symbol,
                    factor=getattr(detector, "name", "UNKNOWN"),
                    status=UNAVAILABLE,
                    unavailable_reason=f"{type(exc).__name__}: {exc}"[:120],
                    observed_at="",
                )
            observations.append(obs)
            if obs.status == TRIGGERED:
                self.stats.observations_triggered += 1
            elif obs.status == UNAVAILABLE:
                self.stats.observations_unavailable += 1
        return observations, True

    def admit(
        self, symbol: str, observations: list[FactorObservation], *, context: dict | None = None
    ) -> FactorCandidate | None:
        """OR admission (§13): one independently triggered factor suffices."""
        triggered = [o for o in observations if o.status == TRIGGERED]
        if not triggered:
            return None
        strongest = max(triggered, key=lambda o: o.strength or 0.0)
        candidate = FactorCandidate(
            symbol=symbol,
            triggered=triggered,
            context=context or {},
            nominated_reason=(
                f"factor scanner detected {strongest.factor} "
                f"(strength {strongest.strength}); "
                f"{len(triggered)} independent factor(s) triggered"
            ),
            priority=strongest.strength or 0.0,
        )
        return candidate

    def scan(self, facts_by_symbol: dict[str, SymbolFacts]) -> list[FactorCandidate]:
        """Scan many symbols; merge multi-factor evidence into one candidate per symbol."""
        candidates: list[FactorCandidate] = []
        self.stats.symbols_scanned = 0
        self.stats.symbols_eligible = 0
        self.stats.observations_triggered = 0
        self.stats.observations_unavailable = 0
        for symbol, facts in facts_by_symbol.items():
            observations, scanned = self.scan_symbol(facts)
            if not scanned:
                continue
            self.stats.symbols_scanned += 1
            self.stats.symbols_eligible += 1
            candidate = self.admit(symbol, observations, context=self._context(facts))
            if candidate is not None:
                candidates.append(candidate)
        # §14: rank by strongest single factor; ties broken by trigger count
        # then liquidity. Priority-only — never admissibility.
        candidates.sort(
            key=lambda c: (
                -(c.triggered[0].strength or 0.0) if c.triggered else 0.0,
                -c.factor_trigger_count,
                -(c.context.get("volume_24h_usd") or 0.0),
            )
        )
        candidates = candidates[: self.max_candidates]
        self.stats.candidates_emitted = len(candidates)
        from datetime import datetime as _dt

        self.stats.last_scan_at = _dt.now(UTC).isoformat()
        return candidates

    @staticmethod
    def _context(facts: SymbolFacts) -> dict:
        return {
            "last_price": facts.last_price,
            "volume_24h_usd": facts.volume_24h_usd,
            "price_change_24h_pct": facts.price_change_24h_pct,
            "funding_rate": facts.funding_rate,
            "oi_change_pct": facts.oi_change_pct,
        }

"""Factor scanner + candidate admission (MASTER DIRECTIVE §4/§13/§14/§15/§24/§39).

Admission is OR-based: ONE independently triggered factor is sufficient to
nominate a symbol as a FactorCandidate. No consensus, no composite
directional score, no minimum factor count (§4/§13).

Multiple triggered factors MERGE into one candidate with richer evidence —
they never become trade signals (§33) and never create authority (§5).

Ranking is priority-only (who ChiefTrader looks at first). It ranks by the
actual priority contract — the strongest single triggered factor — never by
detector declaration order, so a one-strong-factor candidate is neither
suppressed by averaging nor promoted by being declared first (§6.1).
Ranking NEVER decides who may trade.

Rotation (§6.3): fairness is driven by the deep-analysis clock, so persistent
hot factor candidates cannot permanently starve non-factor markets. The same
first rotation symbol is never returned forever: once analyzed it moves to the
back of the fair order.

Authority impact: NONE. A candidate is a research-attention nomination only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

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


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC).isoformat()


@dataclass(slots=True)
class FactorCandidate:
    """A nomination for ChiefTrader review — NEVER an executable signal.

    Every candidate binds to the immutable snapshot that produced it
    (``scan_id`` / ``created_at`` / ``expires_at``), so an expired nomination can
    never be presented as a current opportunity (§6.7).
    """

    symbol: str
    source: str = CANDIDATE_SOURCE_FACTOR_SCANNER
    triggered: list[FactorObservation] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    nominated_reason: str = ""
    priority: float = 0.0
    scan_id: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    pool_reasons: list[str] = field(default_factory=list)
    selection_source: str | None = None

    @property
    def factor_trigger_count(self) -> int:
        return len(self.triggered)

    @property
    def factor_evidence_present(self) -> bool:
        return bool(self.triggered)

    @property
    def strongest_strength(self) -> float:
        """Actual priority contract: strongest single triggered factor."""
        return max((o.strength or 0.0 for o in self.triggered), default=0.0)

    @property
    def strongest_factor(self) -> str | None:
        strongest = max(self.triggered, key=lambda o: o.strength or 0.0, default=None)
        return strongest.factor if strongest is not None else None

    def is_expired(self, *, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        now = now or datetime.now(UTC)
        return now.astimezone(UTC) >= self.expires_at.astimezone(UTC)

    def usable(self, *, now: datetime | None = None) -> bool:
        return self.scan_id is not None and not self.is_expired(now=now)

    def as_dict(self, *, now: datetime | None = None) -> dict:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "selection_source": self.selection_source,
            "scan_id": self.scan_id,
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at),
            "expired": self.is_expired(now=now),
            "factor_trigger_count": self.factor_trigger_count,
            "factor_evidence_present": self.factor_evidence_present,
            "strongest_factor": self.strongest_factor,
            "strongest_strength": round(self.strongest_strength, 6),
            "triggered": [o.as_dict() for o in self.triggered],
            "context": self.context,
            "nominated_reason": self.nominated_reason,
            "pool_reasons": list(self.pool_reasons),
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
    """Fair deep-analysis exposure outside the candidate pool (§6.2/§6.3).

    Independent from the observation clock and the LLM-research clock. When a
    :class:`CoverageLedger` is supplied the next batch is ordered by the oldest
    ``last_analysis_at`` (never-analyzed first), with a consumption cursor
    breaking ties so the same symbol cannot be returned forever. The cursor is
    restart-durable.
    """

    def __init__(self) -> None:
        self._order: list[str] = []
        self._cursor = 0
        self._last_batch: list[str] = []

    def sync(self, symbols: list[str]) -> None:
        known = set(self._order)
        for s in symbols:
            if s not in known:
                self._order.append(s)
        live = set(symbols)
        self._order = [s for s in self._order if s in live]
        if self._cursor >= len(self._order):
            self._cursor = 0

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def last_batch(self) -> list[str]:
        return list(self._last_batch)

    def next_batch(
        self,
        exclude: set[str],
        size: int,
        *,
        ledger=None,
        now=None,
    ) -> list[str]:
        if not self._order or size <= 0:
            self._last_batch = []
            return []
        n = len(self._order)
        # rotate by the consumption cursor first so equal-timestamp ties still
        # advance instead of pinning the same symbol.
        rotated = self._order[self._cursor % n :] + self._order[: self._cursor % n]
        if ledger is not None and now is not None:
            ordered = ledger.oldest_analysis(rotated, limit=len(rotated))
        else:
            ordered = rotated
        picked: list[str] = []
        for sym in ordered:
            if sym in exclude or sym in picked:
                continue
            picked.append(sym)
            if len(picked) >= size:
                break
        # advance the cursor past the last consumed symbol for fairness on ties
        if picked:
            for offset in range(n):
                if rotated[offset] == picked[-1]:
                    self._cursor = (self._cursor + offset + 1) % n
                    break
            else:
                self._cursor = (self._cursor + len(picked)) % n
        self._last_batch = list(picked)
        return picked

    def export_state(self) -> dict:
        return {"order": list(self._order), "cursor": self._cursor}

    def import_state(self, state: dict | None) -> bool:
        if not isinstance(state, dict):
            return False
        order = state.get("order")
        if isinstance(order, list) and all(isinstance(s, str) for s in order):
            self._order = list(order)
            self._cursor = int(state.get("cursor") or 0) % max(1, len(self._order))
            return True
        return False


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
        self,
        symbol: str,
        observations: list[FactorObservation],
        *,
        context: dict | None = None,
        scan_id: str | None = None,
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
        pool_reasons: list[str] | None = None,
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
            scan_id=scan_id,
            created_at=created_at,
            expires_at=expires_at,
            pool_reasons=list(pool_reasons or ["factor candidate"]),
        )
        return candidate

    def scan(
        self,
        facts_by_symbol: dict[str, SymbolFacts],
        *,
        scan_id: str | None = None,
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> list[FactorCandidate]:
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
            candidate = self.admit(
                symbol,
                observations,
                context=self._context(facts),
                scan_id=scan_id,
                created_at=created_at,
                expires_at=expires_at,
            )
            if candidate is not None:
                candidates.append(candidate)
        # §6.1: rank on the actual priority contract — the strongest triggered
        # factor — never on detector declaration order. Ties: trigger count,
        # then liquidity. Priority-only — never admissibility.
        candidates.sort(
            key=lambda c: (
                -c.strongest_strength,
                -c.factor_trigger_count,
                -(c.context.get("volume_24h_usd") or 0.0),
                c.symbol,
            )
        )
        candidates = candidates[: self.max_candidates]
        self.stats.candidates_emitted = len(candidates)
        self.stats.last_scan_at = datetime.now(UTC).isoformat()
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

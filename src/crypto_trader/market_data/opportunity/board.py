"""OpportunityBoard — observable snapshot + audit stats (MASTER DIRECTIVE §29).

Holds the latest scan results in memory and tracks the factual counters that
let operators PROVE (without exposing chain-of-thought or secrets):

    - DeepSeek reviewed factor candidates
    - DeepSeek rejected candidates (NO_TRADE / WAIT)
    - DeepSeek traded WITHOUT factor evidence (Path B is real)
    - DeepSeek traded WITH factor evidence

The board owns NO authority: it is a notice board, not a gate.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from crypto_trader.market_data.opportunity.scanner import FactorCandidate

DECISION_ACTIONS_DIRECTIONAL = {"LONG", "SHORT", "OPEN_LONG", "OPEN_SHORT"}
CANDIDATE_REVIEW_COOLDOWN_SECONDS = 600.0


@dataclass(slots=True)
class DecisionRecord:
    symbol: str
    action: str
    candidate_source: str
    factor_evidence_present: bool
    factor_trigger_count: int
    decision_id: str
    ts: float


@dataclass(slots=True)
class BoardStats:
    decisions_recorded: int = 0
    directional_decisions: int = 0
    directional_with_factor_evidence: int = 0
    directional_without_factor_evidence: int = 0
    candidate_reviews: int = 0
    candidates_rejected_by_deepseek: int = 0
    deepseek_selected_symbols: int = 0

    def as_dict(self) -> dict:
        return {
            "decisions_recorded": self.stats_decisions(),
            "directional_decisions": self.directional_decisions,
            "directional_with_factor_evidence": self.directional_with_factor_evidence,
            "directional_without_factor_evidence": self.directional_without_factor_evidence,
            "candidate_reviews": self.candidate_reviews,
            "candidates_rejected_by_deepseek": self.candidates_rejected_by_deepseek,
            "deepseek_selected_symbols": self.deepseek_selected_symbols,
        }

    def stats_decisions(self) -> int:
        return self.decisions_recorded


@dataclass
class OpportunityBoard:
    """Thread-safe latest opportunity snapshot (evidence-only, no authority)."""

    max_decision_records: int = 500
    candidates: list[FactorCandidate] = field(default_factory=list)
    broad_market: dict = field(default_factory=dict)
    scan_stats: dict = field(default_factory=dict)
    rotation_symbols: list[str] = field(default_factory=list)
    universe_size: int = 0
    eligible_count: int = 0
    updated_at: float = 0.0
    stats: BoardStats = field(default_factory=BoardStats)
    # RLock: snapshot() re-enters recent_decisions() under the same lock.
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _by_symbol: dict[str, FactorCandidate] = field(default_factory=dict)
    _last_review: dict[str, float] = field(default_factory=dict)
    _recent_decisions: list[DecisionRecord] = field(default_factory=list)

    # ---------------------------------------------------------------- publish
    def publish(
        self,
        *,
        candidates: list[FactorCandidate],
        broad_market: dict,
        scan_stats: dict,
        universe_size: int,
        eligible_count: int,
        rotation_symbols: list[str] | None = None,
    ) -> None:
        with self._lock:
            self.candidates = list(candidates)
            self._by_symbol = {c.symbol: c for c in candidates}
            self.broad_market = broad_market
            self.scan_stats = scan_stats
            if rotation_symbols is not None:
                self.rotation_symbols = list(rotation_symbols)
            self.universe_size = universe_size
            self.eligible_count = eligible_count
            self.updated_at = time.time()

    # ------------------------------------------------------------------ read
    def candidate_for(self, symbol: str) -> FactorCandidate | None:
        with self._lock:
            return self._by_symbol.get(symbol)

    def candidate_symbols(self) -> list[str]:
        with self._lock:
            return [c.symbol for c in self.candidates]

    def candidate_review_due(self, symbol: str, *, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            last = self._last_review.get(symbol)
            return last is None or (now - last) >= CANDIDATE_REVIEW_COOLDOWN_SECONDS

    def next_agenda_symbol(
        self,
        *,
        exclude: set[str] | None = None,
        rotation_batch: list[str] | None = None,
    ) -> str | None:
        """Prioritized next symbol for DeepSeek review (scheduling only).

        Order: un-reviewed / cooldown-elapsed factor candidates (by priority),
        then a rotation symbol outside the candidate pool (§39 no starvation).
        """
        now = time.time()
        exclude = exclude or set()
        with self._lock:
            pool = [
                c
                for c in self.candidates
                if c.symbol not in exclude
                and (
                    c.symbol not in self._last_review
                    or (now - self._last_review[c.symbol]) >= CANDIDATE_REVIEW_COOLDOWN_SECONDS
                )
            ]
            if pool:
                return pool[0].symbol
            for sym in rotation_batch if rotation_batch is not None else self.rotation_symbols:
                if sym not in exclude:
                    return sym
        return None

    def mark_reviewed(self, symbol: str) -> None:
        with self._lock:
            self._last_review[symbol] = time.time()

    def record_decision(
        self,
        *,
        symbol: str,
        action: str,
        candidate_source: str,
        factor_evidence_present: bool,
        factor_trigger_count: int,
        decision_id: str,
        deepseek_selected: bool = False,
    ) -> None:
        """Record one DeepSeek decision for §29/§30 observability."""
        rec = DecisionRecord(
            symbol=symbol,
            action=str(action).upper(),
            candidate_source=candidate_source,
            factor_evidence_present=bool(factor_evidence_present),
            factor_trigger_count=int(factor_trigger_count),
            decision_id=decision_id,
            ts=time.time(),
        )
        with self._lock:
            self.stats.decisions_recorded += 1
            if rec.action in DECISION_ACTIONS_DIRECTIONAL:
                self.stats.directional_decisions += 1
                if rec.factor_evidence_present:
                    self.stats.directional_with_factor_evidence += 1
                else:
                    self.stats.directional_without_factor_evidence += 1
            if rec.candidate_source in (
                "FACTOR_SCANNER",
                "MARKET_OBSERVER",
                "DEEPSEEK_SELECTION",
                "POSITION_REVIEW",
            ):
                self.stats.candidate_reviews += 1
                if rec.action in ("NO_TRADE", "WAIT"):
                    self.stats.candidates_rejected_by_deepseek += 1
            if deepseek_selected:
                self.stats.deepseek_selected_symbols += 1
            self._recent_decisions.append(rec)
            if len(self._recent_decisions) > self.max_decision_records:
                del self._recent_decisions[: -self.max_decision_records]

    def recent_decisions(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [
                {
                    "symbol": r.symbol,
                    "action": r.action,
                    "candidate_source": r.candidate_source,
                    "factor_evidence_present": r.factor_evidence_present,
                    "factor_trigger_count": r.factor_trigger_count,
                    "decision_id": r.decision_id,
                    "ts": r.ts,
                }
                for r in self._recent_decisions[-limit:][::-1]
            ]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "universe_size": self.universe_size,
                "eligible_count": self.eligible_count,
                "candidate_count": len(self.candidates),
                "candidates": [c.as_dict() for c in self.candidates],
                "broad_market": self.broad_market,
                "scan_stats": self.scan_stats,
                "rotation_symbols": self.rotation_symbols,
                "stats": self.stats.as_dict(),
                "recent_decisions": self.recent_decisions(50),
                "updated_at": self.updated_at,
                "authority": {
                    "new_direction_decision_authority": "LIVE_LLM_ONLY",
                    "factor_required_for_trade": False,
                    "factor_direction_authority": "NONE",
                },
            }

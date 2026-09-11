"""OpportunityBoard — the latest immutable observation snapshot + audit stats.

The board holds exactly one CURRENT :class:`MarketObservationSnapshot` plus a
bounded history of previous ones. Publishing a new scan REPLACES the reference;
it never mutates an existing snapshot into a future market state (§6.6).

The board owns NO authority: it is a notice board, not a gate. It also tracks
the factual counters that let operators PROVE (without chain-of-thought or
secrets):

    - ChiefTrader reviewed factor candidates
    - ChiefTrader rejected candidates (NO_TRADE / WAIT)
    - ChiefTrader traded WITHOUT factor evidence (Path B is real)
    - ChiefTrader traded WITH factor evidence

Candidate lifecycle (§6.7): every scanner-produced candidate binds to its
``scan_id`` / ``created_at`` / ``expires_at``. Expired candidates remain
historically queryable but are never presented as current opportunities.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.market_data.opportunity.coverage import (
    CoverageLedger,
    MarketSetCounts,
)
from crypto_trader.market_data.opportunity.scanner import FactorCandidate
from crypto_trader.market_data.opportunity.snapshot import (
    DEFAULT_CANDIDATE_TTL_SECONDS,
    STATUS_COMPLETE,
    MarketObservationSnapshot,
    new_scan_id,
    snapshot_expiry,
)

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
    scan_id: str | None = None
    selection_id: str | None = None


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
            "decisions_recorded": self.decisions_recorded,
            "directional_decisions": self.directional_decisions,
            "directional_with_factor_evidence": self.directional_with_factor_evidence,
            "directional_without_factor_evidence": self.directional_without_factor_evidence,
            "candidate_reviews": self.candidate_reviews,
            "candidates_rejected_by_deepseek": self.candidates_rejected_by_deepseek,
            "deepseek_selected_symbols": self.deepseek_selected_symbols,
        }


@dataclass
class OpportunityBoard:
    """Thread-safe latest observation snapshot (evidence-only, no authority)."""

    max_decision_records: int = 500
    max_snapshots: int = 20
    stats: BoardStats = field(default_factory=BoardStats)
    coverage: CoverageLedger = field(default_factory=CoverageLedger)
    market_sets: MarketSetCounts = field(default_factory=MarketSetCounts)
    # legacy scalar mirrors (kept truthful; prefer the explicit market_sets dict)
    universe_size: int = 0
    eligible_count: int = 0
    observable_count: int = 0
    analysis_count: int = 0
    executable_count: int = 0
    selection_service: object | None = None
    # RLock: snapshot() re-enters recent_decisions() under the same lock.
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _snapshot: MarketObservationSnapshot | None = None
    _history: OrderedDict = field(default_factory=OrderedDict)
    _last_review: dict[str, float] = field(default_factory=dict)
    _recent_decisions: list[DecisionRecord] = field(default_factory=list)
    _rotation_symbols: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- publish
    def publish_snapshot(self, snapshot: MarketObservationSnapshot) -> None:
        """Publish one immutable snapshot (new scan_id replaces the current one)."""
        with self._lock:
            self._snapshot = snapshot
            self._history[snapshot.scan_id] = snapshot
            self._rotation_symbols = list(snapshot.rotation_symbols)
            self.universe_size = snapshot.discovered_count
            self.eligible_count = snapshot.execution_supported_count
            self.observable_count = snapshot.observable_count
            self.analysis_count = snapshot.analysis_attempted_count
            self.executable_count = snapshot.execution_supported_count
            while len(self._history) > self.max_snapshots:
                self._history.popitem(last=False)

    def publish(
        self,
        *,
        candidates: list[FactorCandidate],
        broad_market: dict,
        scan_stats: dict,
        universe_size: int,
        eligible_count: int,
        observable_count: int = 0,
        analysis_count: int = 0,
        executable_count: int = 0,
        rotation_symbols: list[str] | None = None,
        status: str = STATUS_COMPLETE,
    ) -> None:
        """Legacy publish path (pre-V1 call sites / focused tests).

        It still creates a real immutable snapshot and BINDS any unbound
        candidate to it, so candidates can never float free of a scan.
        """
        now = datetime.now(UTC)
        scan_id = new_scan_id()
        expires_at = snapshot_expiry(now, DEFAULT_CANDIDATE_TTL_SECONDS)
        bound: list[FactorCandidate] = []
        for candidate in candidates:
            if candidate.scan_id is None:
                candidate.scan_id = scan_id
                candidate.created_at = now
                candidate.expires_at = expires_at
            bound.append(candidate)
        snapshot = MarketObservationSnapshot(
            scan_id=scan_id,
            started_at=now,
            completed_at=now,
            expires_at=expires_at,
            status=status,
            discovered_count=universe_size,
            observable_count=observable_count or len(bound),
            analysis_attempted_count=analysis_count,
            execution_supported_count=executable_count or eligible_count,
            broad_market_summary=broad_market,
            factor_candidates=tuple(bound),
            rotation_symbols=tuple(rotation_symbols or ()),
            data_quality_summary={"legacy_publish_path": True, "scan_stats": scan_stats},
        )
        self.publish_snapshot(snapshot)

    # ------------------------------------------------------------------ read
    def current_snapshot(self) -> MarketObservationSnapshot | None:
        with self._lock:
            return self._snapshot

    @property
    def broad_market(self) -> dict:
        snapshot = self.current_snapshot()
        return dict(snapshot.broad_market_summary) if snapshot else {}

    def historical_snapshot(self, scan_id: str) -> MarketObservationSnapshot | None:
        with self._lock:
            return self._history.get(scan_id)

    def history_ids(self) -> list[str]:
        with self._lock:
            return list(self._history)

    @property
    def rotation_symbols(self) -> list[str]:
        with self._lock:
            return list(self._rotation_symbols)

    def current_candidates(self, *, now: datetime | None = None) -> list[FactorCandidate]:
        snapshot = self.current_snapshot()
        if snapshot is None:
            return []
        return [c for c in snapshot.factor_candidates if not c.is_expired(now=now)]

    def candidate_for(
        self, symbol: str, *, now: datetime | None = None
    ) -> FactorCandidate | None:
        """Current (non-expired) candidate for a symbol, else None."""
        for candidate in self.current_candidates(now=now):
            if candidate.symbol == symbol:
                return candidate
        return None

    def historical_candidate_for(self, symbol: str) -> FactorCandidate | None:
        with self._lock:
            for snapshot in reversed(list(self._history.values())):
                for candidate in snapshot.factor_candidates:
                    if candidate.symbol == symbol:
                        return candidate
        return None

    def candidate_symbols(self, *, now: datetime | None = None) -> list[str]:
        return [c.symbol for c in self.current_candidates(now=now)]

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
        now_wall: float | None = None,
    ) -> str | None:
        """Prioritized next symbol for ChiefTrader review (scheduling only).

        Order: un-reviewed / cooldown-elapsed factor candidates (by the actual
        priority contract), then a fair-rotation symbol outside the candidate
        pool. Expired candidates are never returned.
        """
        now = time.time() if now_wall is None else now_wall
        exclude = exclude or set()
        with self._lock:
            pool = [
                c
                for c in self.current_candidates()
                if c.symbol not in exclude
                and (
                    c.symbol not in self._last_review
                    or (now - self._last_review[c.symbol]) >= CANDIDATE_REVIEW_COOLDOWN_SECONDS
                )
            ]
            pool.sort(key=lambda c: (-c.strongest_strength, -c.factor_trigger_count, c.symbol))
            if pool:
                return pool[0].symbol
            for sym in rotation_batch if rotation_batch is not None else self._rotation_symbols:
                if sym not in exclude:
                    return sym
        return None

    def mark_reviewed(self, symbol: str) -> None:
        with self._lock:
            self._last_review[symbol] = time.time()

    # ------------------------------------------------------------- research
    def mark_llm_research(self, symbol: str, at: datetime | None = None) -> None:
        """Record ChiefTrader deep-research exposure for a symbol (§6.2)."""
        self.coverage.mark_llm_research(symbol, at or datetime.now(UTC))

    def record_risk_approval(self) -> None:
        self.market_sets.record_risk_approval()

    def record_execution(self) -> None:
        self.market_sets.record_execution()

    # ------------------------------------------------------------ decisions
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
        scan_id: str | None = None,
        selection_id: str | None = None,
    ) -> None:
        """Record one ChiefTrader decision for lineage/observability."""
        if scan_id is None:
            snapshot = self.current_snapshot()
            scan_id = snapshot.scan_id if snapshot else None
        rec = DecisionRecord(
            symbol=symbol,
            action=str(action).upper(),
            candidate_source=candidate_source,
            factor_evidence_present=bool(factor_evidence_present),
            factor_trigger_count=int(factor_trigger_count),
            decision_id=decision_id,
            ts=time.time(),
            scan_id=scan_id,
            selection_id=selection_id,
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
                    "scan_id": r.scan_id,
                    "selection_id": r.selection_id,
                    "ts": r.ts,
                }
                for r in self._recent_decisions[-limit:][::-1]
            ]

    # -------------------------------------------------------------- snapshot
    def snapshot(self, *, now: datetime | None = None) -> dict:
        """Wide read-only observability view (no secrets, no chain-of-thought)."""
        now = now or datetime.now(UTC)
        with self._lock:
            snapshot = self._snapshot
            counts = self.market_sets.as_dict()
            if snapshot is None:
                # legacy scalar mirrors are the only available facts
                counts.update(
                    {
                        "discovered_count": self.universe_size,
                        "observable_count": self.observable_count,
                        "analysis_attempted_count": self.analysis_count,
                        "execution_supported_count": self.executable_count
                        or self.eligible_count,
                    }
                )
            return {
                "enabled": True,
                "scan_id": snapshot.scan_id if snapshot else None,
                "snapshot_status": snapshot.status if snapshot else None,
                "snapshot_age_seconds": (
                    round(snapshot.age_seconds(now=now), 3) if snapshot else None
                ),
                "snapshot": snapshot.as_dict() if snapshot else None,
                "snapshot_summary": snapshot.summary_dict() if snapshot else None,
                "universe_size": snapshot.discovered_count if snapshot else 0,
                "eligible_count": snapshot.execution_supported_count if snapshot else 0,
                "market_sets": {
                    # explicit sets (§4) — never conflated
                    **counts,
                    # legacy aliases (pre-V1 clients) — attempted != successful
                    "all_market_count": counts["discovered_count"],
                    "analysis_count": counts["analysis_attempted_count"],
                    "executable_count": counts["execution_supported_count"],
                },
                "candidate_count": len(self.current_candidates(now=now)),
                "candidates": [
                    c.as_dict(now=now) for c in self.current_candidates(now=now)
                ],
                "broad_market": dict(snapshot.broad_market_summary) if snapshot else {},
                "scan_stats": dict(snapshot.data_quality_summary) if snapshot else {},
                "data_quality_summary": (
                    dict(snapshot.data_quality_summary) if snapshot else {}
                ),
                "rotation_symbols": list(self._rotation_symbols),
                "coverage": self.coverage.snapshot(),
                "selection": (
                    self.selection_service.last_record.as_dict()
                    if getattr(self, "selection_service", None) is not None
                    and getattr(self.selection_service, "last_record", None) is not None
                    else None
                ),
                "stats": self.stats.as_dict(),
                "recent_decisions": self.recent_decisions(50),
                "updated_at": (
                    snapshot.completed_at.timestamp() if snapshot else 0.0
                ),
                "authority": {
                    "new_direction_decision_authority": "CHIEF_TRADER_ONLY",
                    "factor_required_for_trade": False,
                    "factor_direction_authority": "NONE",
                },
            }

    def symbol_observability(self, symbol: str) -> dict:
        """Per-symbol coverage clocks + current candidate view (§17)."""
        coverage = self.coverage.as_dict(symbol)
        candidate = self.candidate_for(symbol)
        return {
            "symbol": symbol,
            "last_successful_observation_at": coverage.get("last_successful_observation_at"),
            "last_successful_analysis_at": coverage.get("last_successful_analysis_at"),
            "last_llm_research_at": coverage.get("last_llm_research_at"),
            "candidate": candidate.as_dict() if candidate else None,
        }

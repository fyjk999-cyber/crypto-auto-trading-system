"""Explicit market sets (§4), coverage counters (§6.8) and fairness clocks (§6.2).

Three logically independent fairness clocks are tracked per symbol:

    last_observed_at   — broad factual observation exposure (cheap tickers)
    last_analysis_at   — deep candle/factor analysis exposure (expensive)
    last_llm_research_at — ChiefTrader deep-research exposure

They are never collapsed into a single rotation cursor, and the counters are
never conflated:

    AnalysisAttemptedSet != AnalysisSuccessSet != AnalysisReadySet

Authority impact: NONE. These are scheduling/observability facts only.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ------------------------------------------------------------------ market sets
SET_DISCOVERY_UNIVERSE = "DiscoveryUniverse"
SET_OBSERVABLE = "ObservableSet"
SET_ANALYSIS_ATTEMPTED = "AnalysisAttemptedSet"
SET_ANALYSIS_READY = "AnalysisReadySet"
SET_RESEARCH_EXPOSED = "ResearchExposedSet"
SET_RESEARCH_SELECTED = "ResearchSelectedSet"
SET_EXECUTION_SUPPORTED = "ExecutionSupportedSet"
SET_RISK_APPROVED = "RiskApprovedSet"
SET_EXECUTED = "ExecutedSet"

MARKET_SET_NAMES = (
    SET_DISCOVERY_UNIVERSE,
    SET_OBSERVABLE,
    SET_ANALYSIS_ATTEMPTED,
    SET_ANALYSIS_READY,
    SET_RESEARCH_EXPOSED,
    SET_RESEARCH_SELECTED,
    SET_EXECUTION_SUPPORTED,
    SET_RISK_APPROVED,
    SET_EXECUTED,
)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC).isoformat()


@dataclass(slots=True)
class SymbolCoverage:
    symbol: str
    last_observed_at: datetime | None = None
    last_analysis_at: datetime | None = None
    last_llm_research_at: datetime | None = None
    analysis_attempts: int = 0
    analysis_successes: int = 0
    llm_research_count: int = 0

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "last_observed_at": _iso(self.last_observed_at),
            "last_analysis_at": _iso(self.last_analysis_at),
            "last_llm_research_at": _iso(self.last_llm_research_at),
            "last_successful_observation_at": _iso(self.last_observed_at),
            "last_successful_analysis_at": _iso(self.last_analysis_at),
            "analysis_attempts": self.analysis_attempts,
            "analysis_successes": self.analysis_successes,
            "llm_research_count": self.llm_research_count,
        }


class CoverageLedger:
    """Per-symbol fairness clocks; survives restart via export/import state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._symbols: dict[str, SymbolCoverage] = {}

    def _get(self, symbol: str) -> SymbolCoverage:
        coverage = self._symbols.get(symbol)
        if coverage is None:
            coverage = SymbolCoverage(symbol=symbol)
            self._symbols[symbol] = coverage
        return coverage

    # ------------------------------------------------------------------ writes
    def mark_observed(self, symbol: str, at: datetime) -> None:
        with self._lock:
            self._get(symbol).last_observed_at = at

    def mark_analysis_attempt(self, symbol: str, at: datetime, *, success: bool) -> None:
        with self._lock:
            coverage = self._get(symbol)
            coverage.last_analysis_at = at
            coverage.analysis_attempts += 1
            if success:
                coverage.analysis_successes += 1

    def mark_llm_research(self, symbol: str, at: datetime) -> None:
        with self._lock:
            coverage = self._get(symbol)
            coverage.last_llm_research_at = at
            coverage.llm_research_count += 1

    # ------------------------------------------------------------------- reads
    def get(self, symbol: str) -> SymbolCoverage | None:
        with self._lock:
            return self._symbols.get(symbol)

    def last_analysis_at(self, symbol: str) -> datetime | None:
        with self._lock:
            coverage = self._symbols.get(symbol)
            return coverage.last_analysis_at if coverage else None

    def last_llm_research_at(self, symbol: str) -> datetime | None:
        with self._lock:
            coverage = self._symbols.get(symbol)
            return coverage.last_llm_research_at if coverage else None

    def oldest_researched(
        self, symbols: list[str], *, limit: int, exclude: set[str] | None = None
    ) -> list[str]:
        """Symbols ordered by oldest (or never) ``last_llm_research_at``."""
        exclude = exclude or set()
        with self._lock:
            candidates = [s for s in symbols if s not in exclude]
            candidates.sort(
                key=lambda s: (
                    _aware(self._symbols[s].last_llm_research_at)
                    if s in self._symbols and self._symbols[s].last_llm_research_at
                    else datetime.min.replace(tzinfo=UTC),
                    s,
                )
            )
            return candidates[: max(0, limit)]

    def oldest_analysis(
        self, symbols: list[str], *, limit: int, exclude: set[str] | None = None
    ) -> list[str]:
        exclude = exclude or set()
        with self._lock:
            candidates = [s for s in symbols if s not in exclude]
            candidates.sort(
                key=lambda s: (
                    _aware(self._symbols[s].last_analysis_at)
                    if s in self._symbols and self._symbols[s].last_analysis_at
                    else datetime.min.replace(tzinfo=UTC),
                    s,
                )
            )
            return candidates[: max(0, limit)]

    def oldest_llm_research_at_order(
        self, symbols, *, limit: int | None = None, exclude: set[str] | None = None
    ) -> list[str]:
        """Alias with explicit fairness-clock semantics (§6.2)."""
        symbol_list = list(symbols)
        return self.oldest_researched(
            symbol_list, limit=limit if limit is not None else len(symbol_list), exclude=exclude
        )

    def oldest_analysis_order(
        self, symbols, *, limit: int | None = None, exclude: set[str] | None = None
    ) -> list[str]:
        symbol_list = list(symbols)
        return self.oldest_analysis(
            symbol_list, limit=limit if limit is not None else len(symbol_list), exclude=exclude
        )

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [c.as_dict() for c in self._symbols.values()]

    def as_dict(self, symbol: str) -> dict:
        with self._lock:
            coverage = self._symbols.get(symbol)
        return coverage.as_dict() if coverage else {"symbol": symbol}

    # ------------------------------------------------------ restart durability
    def export_state(self) -> dict:
        def ts(value: datetime | None) -> str | None:
            return _iso(value)

        with self._lock:
            return {
                symbol: {
                    "last_observed_at": ts(c.last_observed_at),
                    "last_analysis_at": ts(c.last_analysis_at),
                    "last_llm_research_at": ts(c.last_llm_research_at),
                    "analysis_attempts": c.analysis_attempts,
                    "analysis_successes": c.analysis_successes,
                    "llm_research_count": c.llm_research_count,
                }
                for symbol, c in self._symbols.items()
            }

    def import_state(self, state: dict | None) -> int:
        if not isinstance(state, dict):
            return 0
        restored = 0

        def parse(value) -> datetime | None:
            if not value:
                return None
            try:
                return datetime.fromisoformat(str(value))
            except ValueError:
                return None

        with self._lock:
            for symbol, row in state.items():
                if not isinstance(row, dict):
                    continue
                coverage = self._get(str(symbol))
                coverage.last_observed_at = parse(row.get("last_observed_at"))
                coverage.last_analysis_at = parse(row.get("last_analysis_at"))
                coverage.last_llm_research_at = parse(row.get("last_llm_research_at"))
                coverage.analysis_attempts = int(row.get("analysis_attempts") or 0)
                coverage.analysis_successes = int(row.get("analysis_successes") or 0)
                coverage.llm_research_count = int(row.get("llm_research_count") or 0)
                restored += 1
        return restored


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass
class MarketSetCounts:
    """Explicit, never-conflated counters (§6.8)."""

    discovered_count: int = 0
    observable_count: int = 0
    analysis_attempted_count: int = 0
    analysis_success_count: int = 0
    analysis_ready_count: int = 0
    research_pool_count: int = 0
    research_selected_count: int = 0
    execution_supported_count: int = 0
    risk_approved_count: int = 0
    executed_count: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def as_dict(self) -> dict:
        with self._lock:
            return {
                "discovered_count": self.discovered_count,
                "observable_count": self.observable_count,
                "analysis_attempted_count": self.analysis_attempted_count,
                "analysis_success_count": self.analysis_success_count,
                "analysis_ready_count": self.analysis_ready_count,
                "research_pool_count": self.research_pool_count,
                "research_selected_count": self.research_selected_count,
                "execution_supported_count": self.execution_supported_count,
                "risk_approved_count": self.risk_approved_count,
                "executed_count": self.executed_count,
                "note_attempted_is_not_success": True,
            }

    def record_scan(
        self,
        *,
        discovered: int,
        observable: int,
        attempted: int,
        success: int,
        ready: int,
        execution_supported: int,
    ) -> None:
        with self._lock:
            self.discovered_count = discovered
            self.observable_count = observable
            self.analysis_attempted_count = attempted
            self.analysis_success_count = success
            self.analysis_ready_count = ready
            self.execution_supported_count = execution_supported

    def record_research_pool(self, count: int) -> None:
        with self._lock:
            self.research_pool_count = int(count)

    def record_research_selected(self, count: int) -> None:
        with self._lock:
            self.research_selected_count = int(count)

    def record_risk_approval(self) -> None:
        with self._lock:
            self.risk_approved_count += 1

    def record_execution(self) -> None:
        with self._lock:
            self.executed_count += 1

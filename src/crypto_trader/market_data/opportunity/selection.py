"""ChiefTrader ACTIVE market selection (§3.2 / §7, Gate 3).

The SAME canonical ChiefTrader that later selects tools and makes the final
LONG/SHORT/WAIT/NO_TRADE decision owns this research-attention phase:

    selection authority   = research attention ONLY
    directional authority = final decision ONLY

Forbidden output fields are rejected at the schema boundary so a selection can
never leak executable trading authority:

    LONG SHORT BUY SELL quantity position_size requested_exposure leverage
    stop_loss take_profit order_type direction side entry exit target signal

Lifecycle (§7.4): one selection per usable ``scan_id``, cooldown-gated
(default 300s), expired scans refused, empty pools reported as errors (a valid
pool may not silently degrade to NO_RESEARCH), LLM unavailability pauses
selection while observation and position management continue.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from crypto_trader.domain.identifiers import new_id
from crypto_trader.llm_chief.budget import (
    P4_MARKET_SELECTION,
    STATUS_OK,
    GlobalLLMBudget,
)
from crypto_trader.market_data.opportunity.directory import (
    MAX_DIRECTORY_PAGES_PER_ROUND,
)
from crypto_trader.market_data.opportunity.pool import PoolEntry, build_research_pool
from crypto_trader.market_data.opportunity.scanner import (
    CANDIDATE_SOURCE_DEEPSEEK_SELECTION as SELECTION_SOURCE_DEEPSEEK,
)
from crypto_trader.market_data.opportunity.snapshot import (
    STATUS_FAILED,
    MarketObservationSnapshot,
)

PROMPT_VERSION = "market-selection-v1"
DEFAULT_COOLDOWN_SECONDS = 300.0
MAX_SELECTED_SYMBOLS = 3
MAX_REQUESTED_DATA = 5
MAX_BRIEF_REASON = 240

STATE_SELECT = "SELECT"
STATE_NO_RESEARCH = "NO_RESEARCH"
# Phase-1 only: the ChiefTrader explicitly asks to explore outside the initial
# pool. It is a request, not a selection — no symbol is selected yet.
STATE_REQUEST_DIRECTORY = "REQUEST_DIRECTORY"
#: legacy spelling accepted when parsing (never emitted)
STATE_SELECTED_LEGACY = "SELECTED"
SELECTION_STATES = (STATE_SELECT, STATE_NO_RESEARCH, STATE_REQUEST_DIRECTORY)
MAX_EXPLORATION_ROUNDS = 1  # hard cap: phase 1 -> (optional directory) -> phase 2

# statuses
ST_SUCCESS = "SUCCESS"
ST_NO_RESEARCH = "NO_RESEARCH"
ST_LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
ST_INVALID_OUTPUT = "INVALID_OUTPUT"
ST_STALE_SCAN = "STALE_SCAN"
ST_SKIPPED_BUDGET = "SKIPPED_BUDGET"
ST_TIMEOUT = "TIMEOUT"
ST_FAILED = "FAILED"
ST_DEFERRED = "DEFERRED"

#: Execution-prerequisite readiness reasons (NEVER directional). A readiness
#: reason only reports that a factual input a TradePlan needs is not available
#: yet; it can never choose LONG/SHORT/WAIT/NO_TRADE.
WARMING_VOLATILITY_UNAVAILABLE = "VOLATILITY_UNAVAILABLE"
WARMING_FEED_NOT_WIRED = "TICKER_FEED_NOT_WIRED"
WARMING_FEED_NOT_REFRESHABLE = "TICKER_FEED_NOT_REFRESHABLE"

#: Same-semantic live ticker warm-up. The realized_volatility contract is the
#: standard deviation of consecutive OKX ticker-snapshot returns, so the only
#: semantically equivalent way to make it available earlier is to drive the
#: SAME ``feed.refresh`` path that the sizing consumer already reads. Closed
#: candles are deliberately NOT used: a 1m bar return and a refresh-spaced
#: ticker return are different sampling intervals, and mixing them would
#: silently change the risk input.
DEFAULT_TICKER_WARMUP_TARGET_SAMPLES = 3
DEFAULT_TICKER_WARMUP_ATTEMPTS = 6
DEFAULT_TICKER_WARMUP_SETTLE_SECONDS = 0.05
DEFAULT_TICKER_WARMUP_MAX_MARGIN_SECONDS = 1.0

FORBIDDEN_SELECTION_FIELDS = frozenset(
    {
        "long",
        "short",
        "buy",
        "sell",
        "action",
        "direction",
        "side",
        "quantity",
        "size",
        "position_size",
        "position_size_request",
        "requested_exposure",
        "exposure",
        "leverage",
        "leverage_request",
        "stop_loss",
        "stop",
        "take_profit",
        "target",
        "order_type",
        "entry",
        "entry_plan",
        "exit",
        "signal",
        "trade",
        "notional",
        "risk",
    }
)

SELECTION_AUTHORITY_NOTE = (
    "You are performing MARKET RESEARCH SELECTION only. Your output grants no "
    "trade direction and no execution. Select 0-3 symbols that deserve deeper "
    "factual research, or return NO_RESEARCH. Never output LONG/SHORT/BUY/SELL, "
    "quantities, leverage, stops, targets or order instructions."
)


class SelectedSymbol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=64)
    brief_reason: str = Field(default="", max_length=MAX_BRIEF_REASON)
    requested_additional_data: list[str] = Field(
        default_factory=list, max_length=MAX_REQUESTED_DATA
    )
    selection_source: str = SELECTION_SOURCE_DEEPSEEK


class DirectoryQuery(BaseModel):
    """Bounded structural directory query (no URLs, no shell, no private data)."""

    model_config = ConfigDict(extra="forbid")

    sort: Literal["estimated_turnover", "abs_move", "symbol"] = "estimated_turnover"
    page: int = Field(default=1, ge=1, le=MAX_DIRECTORY_PAGES_PER_ROUND)
    min_abs_move_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    min_estimated_turnover: float | None = Field(default=None, ge=0.0)
    funding_side: Literal["positive", "negative", "any"] | None = None
    note: str = Field(default="", max_length=160)


class MarketSelectionOutput(BaseModel):
    """Strict two-phase selection contract — no trading-authority fields.

    Phase 1 may return SELECT / NO_RESEARCH / REQUEST_DIRECTORY.
    Phase 2 (after the system executed the bounded directory lookup) may return
    only SELECT / NO_RESEARCH — there is no third exploration phase in V1.
    """

    model_config = ConfigDict(extra="forbid")

    selection_id: str
    scan_id: str
    selection_state: Literal["SELECT", "NO_RESEARCH", "REQUEST_DIRECTORY"]
    selected_symbols: list[SelectedSymbol] = Field(
        default_factory=list, max_length=MAX_SELECTED_SYMBOLS
    )
    directory_query: DirectoryQuery | None = None

    def model_post_init(self, __context) -> None:  # noqa: D105
        if self.selection_state == STATE_REQUEST_DIRECTORY:
            if self.selected_symbols:
                raise ValueError("REQUEST_DIRECTORY must not select symbols")
            if self.directory_query is None:
                raise ValueError("REQUEST_DIRECTORY requires a bounded directory_query")
            return
        if self.selection_state == STATE_NO_RESEARCH and self.selected_symbols:
            raise ValueError("NO_RESEARCH must not contain selected symbols")
        if self.selection_state == STATE_SELECT and not self.selected_symbols:
            raise ValueError("SELECT requires at least one symbol")
        if self.directory_query is not None:
            raise ValueError("directory_query is only valid with REQUEST_DIRECTORY")
        symbols = [s.symbol for s in self.selected_symbols]
        if len(symbols) != len(set(symbols)):
            raise ValueError("duplicate selected symbols")

    @property
    def is_exploration_request(self) -> bool:
        return self.selection_state == STATE_REQUEST_DIRECTORY

    @property
    def is_terminal(self) -> bool:
        return self.selection_state in (STATE_SELECT, STATE_NO_RESEARCH)


def find_authority_leak(payload: Any, *, path: str = "") -> str | None:
    """Return the first forbidden trading-authority field, if any."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_l = str(key).strip().lower()
            if key_l in FORBIDDEN_SELECTION_FIELDS:
                return f"{path}{key}"
            found = find_authority_leak(value, path=f"{path}{key}.")
            if found:
                return found
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            found = find_authority_leak(item, path=f"{path}[{index}].")
            if found:
                return found
    return None


@dataclass(slots=True)
class MarketSelectionRecord:
    """Durable record of one selection round (§12). No chain-of-thought."""

    selection_id: str
    scan_id: str
    status: str
    selection_state: str = ""
    provider: str | None = None
    model: str | None = None
    prompt_version: str = PROMPT_VERSION
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    candidate_set_ref: str | None = None
    directory_query_refs: list[str] = field(default_factory=list)
    selected_symbols: list[dict] = field(default_factory=list)
    selection_source: str = SELECTION_SOURCE_DEEPSEEK
    error_code: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    snapshot_age_seconds: float | None = None
    pool_size: int = 0
    exploration_rounds: int = 0
    directory_query: dict = field(default_factory=dict)

    @property
    def selected_symbol_names(self) -> list[str]:
        return [str(s.get("symbol")) for s in self.selected_symbols]

    def as_dict(self) -> dict:
        return {
            "selection_id": self.selection_id,
            "scan_id": self.scan_id,
            "status": self.status,
            "selection_state": self.selection_state,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "requested_at": self.requested_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "candidate_set_ref": self.candidate_set_ref,
            "directory_query_refs": list(self.directory_query_refs),
            "selected_symbols": [dict(s) for s in self.selected_symbols],
            "selection_source": self.selection_source,
            "error_code": self.error_code,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "snapshot_age_seconds": self.snapshot_age_seconds,
            "pool_size": self.pool_size,
            "exploration_rounds": self.exploration_rounds,
            "directory_query": dict(self.directory_query),
            "authority": {
                "selection_authority": "RESEARCH_ATTENTION_ONLY",
                "directional_authority": "NONE",
                "new_direction_decision_authority": "CHIEF_TRADER_FINAL_PHASE_ONLY",
            },
        }


PHASE_INITIAL = "INITIAL_POOL"
PHASE_EXPLORATION = "DIRECTORY_EXPLORATION"


def build_selection_context(
    *,
    snapshot: MarketObservationSnapshot,
    pool: list[PoolEntry],
    directory_pages: list[dict],
    existing_positions: list[str],
    budget_state: dict,
    cooldown_remaining_seconds: float,
    last_selection: dict | None,
    now: datetime,
    phase: str = PHASE_INITIAL,
    directory_symbol_pages: dict[str, int] | None = None,
) -> dict:
    """Compact, bounded selection context.

    Phase 1 carries ONLY the initial pool (no directory pages) so the
    ChiefTrader must actively REQUEST_DIRECTORY to explore. Phase 2 carries the
    bounded directory result of that request and is terminal.
    """
    context = {
        "scan_id": snapshot.scan_id,
        "snapshot_age_seconds": round(snapshot.age_seconds(now=now), 3),
        "snapshot_status": snapshot.status,
        "snapshot_expires_at": snapshot.expires_at.isoformat(),
        "universe_type": snapshot.universe_type,
        "market_set_counts": {
            "discovered_count": snapshot.discovered_count,
            "observable_count": snapshot.observable_count,
            "analysis_attempted_count": snapshot.analysis_attempted_count,
            "analysis_success_count": snapshot.analysis_success_count,
            "analysis_ready_count": snapshot.analysis_ready_count,
            "execution_supported_count": snapshot.execution_supported_count,
        },
        "phase": phase,
        "candidate_pool": [entry.as_dict() for entry in pool],
        "candidate_pool_size": len(pool),
        "broad_market_summary": {
            "rows_observed": (snapshot.broad_market_summary or {}).get("rows_observed"),
            "top_abs_movers_24h": (snapshot.broad_market_summary or {}).get(
                "top_abs_movers_24h", []
            ),
        },
        "data_quality_summary": {
            "funding": (snapshot.data_quality_summary or {}).get("funding", {}),
            "open_interest": (snapshot.data_quality_summary or {}).get("open_interest", {}),
            "notes": (snapshot.data_quality_summary or {}).get("notes", []),
        },
        "feature_coverage": dict(getattr(snapshot, "feature_coverage", {}) or {}),
        "existing_positions": list(existing_positions),
        "execution_supported_label": "USDT linear perpetual swaps only (PAPER)",
        "global_llm_budget": {
            "calls_in_window": budget_state.get("calls_in_window"),
            "remaining": budget_state.get("remaining"),
        },
        "last_selection": last_selection,
        "authority_note": SELECTION_AUTHORITY_NOTE,
        "output_contract": {
            "selection_state": "SELECT | NO_RESEARCH | REQUEST_DIRECTORY",
            "selected_symbols": [
                {
                    "symbol": "string",
                    "brief_reason": "short factual reason",
                    "requested_additional_data": ["optional bounded requests"],
                }
            ],
            "directory_query": {
                "sort": "estimated_turnover | abs_move | symbol",
                "page": "1..2",
                "min_abs_move_pct": "optional number",
                "min_estimated_turnover": "optional number",
                "funding_side": "positive | negative | any (optional)",
            },
            "maximum_selected_symbols": MAX_SELECTED_SYMBOLS,
            "maximum_directory_pages": MAX_DIRECTORY_PAGES_PER_ROUND,
        },
    }
    if phase == PHASE_EXPLORATION and directory_pages:
        context["market_directory"] = {
            "pages": directory_pages,
            "symbol_pages": dict(directory_symbol_pages or {}),
            "note": (
                "read-only factual directory result for YOUR exploration request. "
                "This is the FINAL phase: return SELECT (0-3 symbols) or NO_RESEARCH."
            ),
        }
    return context


class MarketSelectionService:
    """Owns the selection lifecycle; calls the SAME ChiefTrader engine."""

    def __init__(
        self,
        *,
        board,
        chief,
        budget: GlobalLLMBudget | None = None,
        store=None,
        directory=None,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        pool_size: int = 30,
        timeout_seconds: float = 40.0,
        clock=None,
        ticker_feed=None,
        ticker_warmup_target_samples: int = DEFAULT_TICKER_WARMUP_TARGET_SAMPLES,
        ticker_warmup_attempts: int = DEFAULT_TICKER_WARMUP_ATTEMPTS,
    ) -> None:
        self.board = board
        self.chief = chief
        self.budget = budget
        self.store = store
        self.directory = directory
        self.cooldown_seconds = float(cooldown_seconds)
        self.pool_size = int(pool_size)
        self.timeout_seconds = float(timeout_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self.ticker_feed = ticker_feed
        self.ticker_warmup_target_samples = max(1, int(ticker_warmup_target_samples))
        self.ticker_warmup_attempts = max(1, int(ticker_warmup_attempts))
        self.ticker_warmup_status: dict[str, dict] = {}
        self._last_autonomous_selection_at: datetime | None = None
        self._last_selection_id_by_scan: dict[str, str] = {}
        self._records_by_scan: dict[str, MarketSelectionRecord] = {}
        self.selection_count = 0
        self.last_record: MarketSelectionRecord | None = None
        self.last_query_ref: str | None = None

    # ------------------------------------------------------------------ read
    def last_selection_for_scan(self, scan_id: str) -> MarketSelectionRecord | None:
        if self.store is not None:
            found = self.store.cached_for_scan(scan_id)
            if found is not None:
                return found
        return None

    def cooldown_remaining_seconds(self, *, now: datetime) -> float:
        if self._last_autonomous_selection_at is None:
            return 0.0
        elapsed = (now - self._last_autonomous_selection_at).total_seconds()
        return max(0.0, self.cooldown_seconds - elapsed)

    # ----------------------------------------------------------------- select
    async def maybe_select(
        self,
        *,
        existing_positions: list[str] | None = None,
        now: datetime | None = None,
    ) -> MarketSelectionRecord:
        now = now or self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        snapshot = self.board.current_snapshot()
        if snapshot is None:
            return self._record_local(
                MarketSelectionRecord(
                    selection_id=new_id("mkt_sel"),
                    scan_id="none",
                    status=ST_STALE_SCAN,
                    error_code="NO_SNAPSHOT",
                    requested_at=now,
                    completed_at=now,
                )
            )
        age = snapshot.age_seconds(now=now)
        record = MarketSelectionRecord(
            selection_id=new_id("mkt_sel"),
            scan_id=snapshot.scan_id,
            status=ST_FAILED,
            requested_at=now,
            snapshot_age_seconds=age,
        )
        if snapshot.status == STATUS_FAILED:
            record.status = ST_STALE_SCAN
            record.error_code = "SNAPSHOT_FAILED"
            return await self._persist(record, now=now)
        if snapshot.is_expired(now=now):
            record.status = ST_STALE_SCAN
            record.error_code = "SNAPSHOT_EXPIRED"
            return await self._persist(record, now=now)

        # duplicate guard: same scan_id never produces two autonomous selections
        existing = self._records_by_scan.get(snapshot.scan_id)
        if existing is None and self.store is not None:
            existing = self.store.cached_for_scan(snapshot.scan_id)
        if existing is not None and existing.status in (ST_SUCCESS, ST_NO_RESEARCH):
            return existing

        cooldown_remaining = self.cooldown_remaining_seconds(now=now)
        if cooldown_remaining > 0:
            record.status = ST_DEFERRED
            record.error_code = "SELECTION_COOLDOWN_ACTIVE"
            return await self._persist(record, now=now)

        pool = build_research_pool(
            snapshot=snapshot,
            ledger=self.board.coverage,
            max_size=self.pool_size,
            existing_positions=set(existing_positions or ()),
            now=now,
        )
        self.board.market_sets.record_research_pool(len(pool))
        record.pool_size = len(pool)
        if not pool:
            # a valid snapshot with no researchable market is an error state,
            # never a silent NO_RESEARCH
            record.status = ST_FAILED
            record.error_code = "EMPTY_RESEARCH_POOL"
            return await self._persist(record, now=now)

        budget_state = self.budget.snapshot() if self.budget else {"enabled": False}
        ticket = None
        if self.budget is not None:
            ticket = self.budget.try_acquire(P4_MARKET_SELECTION, operation="market_selection")
            budget_state = self.budget.snapshot()
            if not ticket.granted:
                record.status = ST_SKIPPED_BUDGET
                record.error_code = "LLM_BUDGET_RESERVED_FOR_HIGHER_PRIORITY"
                return await self._persist(record, now=now)

        # ---- phase 1: initial pool only (NO preloaded directory) -----------
        record.candidate_set_ref = f"pool:{snapshot.scan_id}:{len(pool)}"
        context = build_selection_context(
            snapshot=snapshot,
            pool=pool,
            directory_pages=[],
            existing_positions=list(existing_positions or ()),
            budget_state=budget_state,
            cooldown_remaining_seconds=cooldown_remaining,
            last_selection=self.last_record.as_dict() if self.last_record else None,
            now=now,
            phase=PHASE_INITIAL,
        )
        started = self._clock()
        try:
            result = await self.chief.select_markets(
                context,
                timeout_seconds=self.timeout_seconds,
                selection_id=record.selection_id,
                scan_id=snapshot.scan_id,
            )
        except TimeoutError:
            record.status = ST_TIMEOUT
            record.error_code = "SELECTION_TIMEOUT"
            record.completed_at = self._clock()
            record.latency_ms = self._latency_ms(started)
            if ticket:
                ticket.fail(status="TIMEOUT")
            return await self._persist(record, now=now)
        except Exception as exc:  # any provider explosion fails closed
            record.status = ST_FAILED
            record.error_code = f"{type(exc).__name__}"[:64]
            record.completed_at = self._clock()
            if ticket:
                ticket.fail(status="ERROR", detail=record.error_code)
            return await self._persist(record, now=now)

        record.provider = result.provider
        record.model = result.model
        record.input_tokens = result.input_tokens
        record.output_tokens = result.output_tokens
        record.latency_ms = result.latency_ms
        record.completed_at = self._clock()
        _complete_ticket(ticket, result)

        if not result.ok:
            record.status = result.status
            record.error_code = result.error_code
            return await self._persist(record, now=now)

        directory_pages: list[dict] = []
        directory_symbol_pages: dict[str, int] = {}

        # ---- optional bounded directory exploration by the SAME chief ------
        if result.output.is_exploration_request:
            exploration = await self._explore_directory(
                record=record,
                snapshot=snapshot,
                result=result,
                pool=pool,
                existing_positions=list(existing_positions or ()),
                now=now,
            )
            if isinstance(exploration, str):
                record.status = (
                    ST_DEFERRED if exploration == "SKIPPED_BUDGET" else ST_INVALID_OUTPUT
                )
                record.error_code = exploration
                record.completed_at = self._clock()
                return await self._persist(record, now=now)
            directory_pages, directory_symbol_pages, phase2 = exploration
            if not phase2.ok:
                record.status = phase2.status
                record.error_code = phase2.error_code
                return await self._persist(record, now=now)
            result = phase2
            record.input_tokens = (record.input_tokens or 0) + (result.input_tokens or 0)
            record.output_tokens = (record.output_tokens or 0) + (result.output_tokens or 0)
            record.latency_ms = (record.latency_ms or 0) + (result.latency_ms or 0)
            record.exploration_rounds = 1
            record.completed_at = self._clock()

        selected = self._materialize(
            result.output, pool=pool, directory_pages=directory_pages,
            directory_symbol_pages=directory_symbol_pages,
        )
        if isinstance(selected, str):
            record.status = ST_INVALID_OUTPUT
            record.error_code = selected
            return await self._persist(record, now=now)

        record.selection_state = result.output.selection_state
        record.selected_symbols = selected
        if result.output.selection_state == STATE_NO_RESEARCH:
            record.status = ST_NO_RESEARCH
        else:
            record.status = ST_SUCCESS
            warmup_symbols: list[str] = []
            for entry in selected:
                symbol = str(entry["symbol"])
                warmup_symbols.append(symbol)
                self.board.coverage.mark_llm_research(symbol, now)
                self.board.market_sets.record_research_selected(len(selected))
            # Same-semantic live ticker warm-up BEFORE these symbols become
            # eligible for directional research. The consumer queue hands a
            # selected symbol to the ChiefTrader on the very next tick, so
            # without this the first directional decision on any newly
            # observed symbol would reach sizing with
            # realized_volatility=None and fail closed.
            await self._warm_ticker_observations(warmup_symbols)
        self._last_autonomous_selection_at = now
        return await self._persist(record, now=now)

    # -------------------------------------------------- ticker warm-up (§D5)
    def _ticker_sample_count(self, symbol: str) -> int:
        """Factual ticker observations already accumulated for ``symbol``.

        Reads the EXISTING producer buffer; no second cache is created.
        """
        feed = self.ticker_feed
        history = getattr(feed, "_price_history", None)
        if not isinstance(history, dict):
            return 0
        return len(history.get(symbol) or ())

    def ticker_warmup_readiness(self, symbol: str) -> str:
        """Report execution-prerequisite readiness. NEVER a direction.

        Returns ``READY`` when the symbolic volatility input can be produced
        (>= 3 ticker observations => >= 2 returns, matching the producer
        contract), otherwise ``WARMING``.
        """
        if self.ticker_feed is None:
            return WARMING_FEED_NOT_WIRED
        if self._ticker_sample_count(symbol) >= self.ticker_warmup_target_samples:
            return "READY"
        return "WARMING"

    async def _warm_ticker_observations(self, symbols: list[str]) -> None:
        """Drive the SAME ``feed.refresh`` path so factual ticker observations
        reach the volatility producer's minimum sample count.

        Guarantees:
            * a symbol's refresh is never issued faster than the feed's own
              ``min_refresh_interval`` (no provider spam),
            * no price is synthesised, duplicated or back-dated,
            * any failure degrades to ``WARMING`` and never blocks selection,
            * the volatility algorithm itself is untouched.
        """
        feed = self.ticker_feed
        if feed is None or not symbols:
            return
        refresh = getattr(feed, "refresh", None)
        if not callable(refresh):
            return
        interval_seconds = getattr(
            getattr(feed, "min_refresh_interval", None), "total_seconds", None
        )
        interval = (
            max(0.0, float(interval_seconds()))
            if callable(interval_seconds)
            else DEFAULT_TICKER_WARMUP_MAX_MARGIN_SECONDS
        )
        gap = interval + DEFAULT_TICKER_WARMUP_SETTLE_SECONDS
        for symbol in symbols:
            try:
                samples = self._ticker_sample_count(symbol)
                attempts = 0
                while (
                    samples < self.ticker_warmup_target_samples
                    and attempts < self.ticker_warmup_attempts
                ):
                    if attempts:
                        await asyncio.sleep(gap)
                    await refresh(symbol)
                    attempts += 1
                    samples = self._ticker_sample_count(symbol)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # readiness is best-effort, never fatal
                self.ticker_warmup_status[symbol] = {
                    "status": "WARMING",
                    "reason": type(exc).__name__,
                    "samples": self._ticker_sample_count(symbol),
                }
                continue
            ready = samples >= self.ticker_warmup_target_samples
            self.ticker_warmup_status[symbol] = {
                "status": "READY" if ready else "WARMING",
                "reason": None if ready else WARMING_VOLATILITY_UNAVAILABLE,
                "samples": samples,
                "attempts": attempts,
            }

    # -------------------------------------------------------------- internals
    async def _explore_directory(
        self, *, record, snapshot, result, pool, existing_positions, now
    ):
        """Execute ONE bounded read-only directory lookup for the same chief.

        Hard limits: at most 2 pages of <=25 rows. The second model call is the
        SAME ChiefTrader and is terminal (no third exploration phase). The
        exploration call consumes P4 budget like any other market-selection call
        and fails closed when no P4 capacity remains.
        """
        if self.directory is None:
            return "DIRECTORY_UNAVAILABLE"
        if record.exploration_rounds >= MAX_EXPLORATION_ROUNDS:
            return "EXPLORATION_ROUND_LIMIT"

        # budget: the follow-up call is a second model call at the same priority
        ticket = None
        if self.budget is not None:
            ticket = self.budget.try_acquire(
                P4_MARKET_SELECTION, operation="market_directory_exploration"
            )
            if not ticket.granted:
                return "SKIPPED_BUDGET"

        query = result.output.directory_query
        query_payload = query.model_dump(mode="json") if query is not None else {}
        pages, refs, symbol_pages = self.directory.query_pages(
            query_payload,
            scan_id=snapshot.scan_id,
            exclude={e.symbol for e in pool},
            now=now,
        )
        record.directory_query_refs = list(refs)
        record.directory_query = _compact_query(query_payload)
        self.last_query_ref = "|".join(
            f"{key}={value}" for key, value in record.directory_query.items()
        ) or "default"

        context = build_selection_context(
            snapshot=snapshot,
            pool=pool,
            directory_pages=pages,
            existing_positions=list(existing_positions or ()),
            budget_state=self.budget.snapshot() if self.budget else {"enabled": False},
            cooldown_remaining_seconds=0.0,
            last_selection=self.last_record.as_dict() if self.last_record else None,
            now=now,
            phase=PHASE_EXPLORATION,
            directory_symbol_pages=symbol_pages,
        )
        try:
            phase2 = await self.chief.select_markets(
                context,
                timeout_seconds=self.timeout_seconds,
                selection_id=record.selection_id,
                scan_id=snapshot.scan_id,
            )
        except TimeoutError:
            if ticket:
                ticket.fail(status="TIMEOUT")
            return "EXPLORATION_TIMEOUT"
        except Exception as exc:
            if ticket:
                ticket.fail(status="ERROR", detail=type(exc).__name__)
            return f"EXPLORATION_FAILED:{type(exc).__name__}"[:64]
        _complete_ticket(ticket, phase2)
        if not phase2.ok:
            return phase2
        if not phase2.output.is_terminal:
            # V1 allows exactly one exploration round: a second
            # REQUEST_DIRECTORY is an invalid output, not a new loop.
            return "NO_THIRD_EXPLORATION_PHASE"
        return pages, symbol_pages, phase2

    def _materialize(
        self,
        output: MarketSelectionOutput,
        *,
        pool: list[PoolEntry],
        directory_pages: list[dict],
        directory_symbol_pages: dict[str, int] | None = None,
    ) -> list[dict] | str:
        pool_by_symbol = {entry.symbol: entry for entry in pool}
        directory_symbols = {
            row.get("symbol")
            for page in directory_pages
            for row in (page.get("rows") or ())
        }
        directory_symbol_pages = directory_symbol_pages or {}
        materialized: list[dict] = []
        for item in output.selected_symbols:
            symbol = item.symbol.strip()
            if symbol in pool_by_symbol:
                # supplied by the program in the initial pool: NOT a discovery
                pool_reasons = list(pool_by_symbol[symbol].reasons)
                materialized.append(
                    {
                        "symbol": symbol,
                        "brief_reason": item.brief_reason[:MAX_BRIEF_REASON],
                        "requested_additional_data": list(item.requested_additional_data)[
                            :MAX_REQUESTED_DATA
                        ],
                        "selection_source": SELECTION_SOURCE_DEEPSEEK,
                        "pool_reasons": pool_reasons,
                        "from_initial_pool": True,
                        "discovered_via_directory": False,
                    }
                )
                continue
            if symbol in directory_symbols:
                # §10: actively discovered by ChiefTrader directory exploration
                page_number = directory_symbol_pages.get(symbol)
                query_ref = (
                    f"market_directory_query:{output.scan_id}:"
                    f"{self.last_query_ref or 'page'}"
                )
                materialized.append(
                    {
                        "symbol": symbol,
                        "brief_reason": item.brief_reason[:MAX_BRIEF_REASON],
                        "requested_additional_data": list(item.requested_additional_data)[
                            :MAX_REQUESTED_DATA
                        ],
                        "selection_source": SELECTION_SOURCE_DEEPSEEK,
                        "pool_reasons": ["market directory"],
                        "from_initial_pool": False,
                        "discovered_via_directory": True,
                        "directory_query_ref": query_ref,
                        "directory_page_ref": (
                            f"market_directory:{output.scan_id}:page={page_number}"
                            if page_number is not None
                            else None
                        ),
                    }
                )
                continue
            return f"SELECTED_SYMBOL_NOT_IN_CONTEXT:{symbol}"[:64]
        return materialized

    def _latency_ms(self, started: datetime) -> int:
        return int((self._clock() - started).total_seconds() * 1000)

    def _record_local(self, record: MarketSelectionRecord) -> MarketSelectionRecord:
        self.last_record = record
        return record

    async def _persist(
        self, record: MarketSelectionRecord, *, now: datetime
    ) -> MarketSelectionRecord:
        if record.completed_at is None:
            record.completed_at = now
        self.last_record = record
        self.selection_count += 1
        self._last_selection_id_by_scan[record.scan_id] = record.selection_id
        if record.status in (ST_SUCCESS, ST_NO_RESEARCH):
            self._records_by_scan[record.scan_id] = record
            while len(self._records_by_scan) > 50:
                self._records_by_scan.pop(next(iter(self._records_by_scan)), None)
        if self.store is not None:
            await self.store.save(record)
        return record


def _complete_ticket(ticket, result) -> None:
    """Record the outcome of one budgeted market-selection model call."""
    if ticket is None:
        return
    ticket.complete(
        status=STATUS_OK if result.ok else "ERROR",
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        latency_ms=result.latency_ms,
        detail=result.error_code,
    )


def _compact_query(query: dict) -> dict:
    """Bounded, non-secret summary of the structural directory query."""
    return {
        key: query.get(key)
        for key in (
            "sort",
            "page",
            "min_abs_move_pct",
            "min_estimated_turnover",
            "funding_side",
        )
        if query.get(key) is not None
    }


def parse_selection_payload(
    payload: Any,
    *,
    selection_id: str,
    scan_id: str,
    known_symbols: set[str] | None = None,
) -> MarketSelectionOutput | str:
    """Strictly validate a raw model payload; returns output or an error code."""
    if not isinstance(payload, dict):
        return "INVALID_OUTPUT_NOT_OBJECT"
    leak = find_authority_leak(payload)
    if leak:
        return f"AUTHORITY_LEAK:{leak}"[:64]
    candidate = dict(payload)
    candidate["selection_id"] = selection_id
    candidate["scan_id"] = scan_id
    # normalise a couple of friendly spellings before strict validation
    if "selection_state" not in candidate and "state" in candidate:
        candidate["selection_state"] = candidate.pop("state")
    if "selected_symbols" not in candidate and "symbols" in candidate:
        candidate["selected_symbols"] = candidate.pop("symbols")
    state = str(candidate.get("selection_state") or "").upper()
    if state in {"NO_RESEARCH", "NO RESEARCH", "NONE", "NO_SELECTION"}:
        candidate["selection_state"] = STATE_NO_RESEARCH
        candidate["selected_symbols"] = []
        candidate.pop("directory_query", None)
    elif state in {"SELECTED", "SELECT"}:
        candidate["selection_state"] = STATE_SELECT
        symbols = candidate.get("selected_symbols")
        if isinstance(symbols, list):
            candidate["selected_symbols"] = [
                {"symbol": s} if isinstance(s, str) else s for s in symbols
            ]
        candidate.pop("directory_query", None)
    elif state in {"REQUEST_DIRECTORY", "REQUEST DIRECTORY", "EXPLORE", "DIRECTORY"}:
        candidate["selection_state"] = STATE_REQUEST_DIRECTORY
        candidate["selected_symbols"] = []
        query = candidate.get("directory_query") or {}
        if not isinstance(query, dict):
            return "INVALID_DIRECTORY_QUERY"
        # bounded structural fields only — never a raw URL / provider call
        allowed = {
            "sort",
            "page",
            "min_abs_move_pct",
            "min_estimated_turnover",
            "funding_side",
            "note",
        }
        unexpected = set(query) - allowed
        if unexpected:
            return f"INVALID_DIRECTORY_QUERY:{sorted(unexpected)[0]}"[:64]
        candidate["directory_query"] = query
    try:
        output = MarketSelectionOutput(**candidate)
    except (ValidationError, ValueError) as exc:
        return f"INVALID_OUTPUT:{type(exc).__name__}"[:64]
    if known_symbols is not None:
        for item in output.selected_symbols:
            if item.symbol not in known_symbols:
                return f"UNKNOWN_SYMBOL:{item.symbol}"[:64]
    return output


def render_selection_prompt(context: dict) -> str:
    """Phase-aware prompt for the SAME ChiefTrader market-selection authority."""
    phase = str(context.get("phase") or PHASE_INITIAL)
    if phase == PHASE_EXPLORATION:
        instructions = (
            "This is the FINAL phase. You requested bounded directory exploration "
            "and the factual result is in market_directory. You may NOT request "
            "exploration again. Return JSON only as:\n"
            '{"selection_state":"SELECT|NO_RESEARCH","selected_symbols":'
            '[{"symbol":"...","brief_reason":"...","requested_additional_data":["..."]}]}\n'
            f"Select at most {MAX_SELECTED_SYMBOLS} symbols, or NO_RESEARCH with an "
            "empty selected_symbols list.\n"
        )
    else:
        instructions = (
            "You have a bounded initial candidate pool. Choose ONE of:\n"
            '  {"selection_state":"SELECT","selected_symbols":[{"symbol":"...",'
            '"brief_reason":"...","requested_additional_data":["..."]}]}\n'
            '  {"selection_state":"NO_RESEARCH","selected_symbols":[]}\n'
            '  {"selection_state":"REQUEST_DIRECTORY","directory_query":'
            '{"sort":"estimated_turnover|abs_move|symbol","page":1,'
            '"min_abs_move_pct":null,"min_estimated_turnover":null,'
            '"funding_side":"positive|negative|any"}}\n'
            "REQUEST_DIRECTORY asks the system to run ONE bounded read-only "
            f"directory lookup (max {MAX_DIRECTORY_PAGES_PER_ROUND} pages, "
            f"max {MAX_DIRECTORY_PAGES_PER_ROUND} pages, page size <= 25) so you "
            "can see markets outside the initial pool before the final selection.\n"
            f"Select at most {MAX_SELECTED_SYMBOLS} symbols when you SELECT. "
            "Keep brief_reason short.\n"
        )
    return (
        "You are the Chief Trader selecting WHERE TO SPEND RESEARCH ATTENTION.\n"
        "This is NOT a trade decision. Return JSON only.\n"
        f"{SELECTION_AUTHORITY_NOTE}\n"
        f"{instructions}"
        f"MarketSelectionContext: {json.dumps(context, default=str)}"
    )

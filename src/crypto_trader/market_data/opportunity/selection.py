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

STATE_SELECTED = "SELECTED"
STATE_NO_RESEARCH = "NO_RESEARCH"

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


class MarketSelectionOutput(BaseModel):
    """Strict selection output contract — no trading-authority fields."""

    model_config = ConfigDict(extra="forbid")

    selection_id: str
    scan_id: str
    selection_state: Literal["SELECTED", "NO_RESEARCH"]
    selected_symbols: list[SelectedSymbol] = Field(
        default_factory=list, max_length=MAX_SELECTED_SYMBOLS
    )

    def model_post_init(self, __context) -> None:  # noqa: D105
        if self.selection_state == STATE_NO_RESEARCH and self.selected_symbols:
            raise ValueError("NO_RESEARCH must not contain selected symbols")
        if self.selection_state == STATE_SELECTED and not self.selected_symbols:
            raise ValueError("SELECTED requires at least one symbol")
        symbols = [s.symbol for s in self.selected_symbols]
        if len(symbols) != len(set(symbols)):
            raise ValueError("duplicate selected symbols")


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
            "authority": {
                "selection_authority": "RESEARCH_ATTENTION_ONLY",
                "directional_authority": "NONE",
                "new_direction_decision_authority": "CHIEF_TRADER_FINAL_PHASE_ONLY",
            },
        }


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
) -> dict:
    """Compact, bounded selection context (§7.2). Never full histories."""
    return {
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
        "candidate_pool": [entry.as_dict() for entry in pool],
        "candidate_pool_size": len(pool),
        "broad_market_summary": dict(snapshot.broad_market_summary),
        "data_quality_summary": dict(snapshot.data_quality_summary),
        "existing_positions": list(existing_positions),
        "execution_supported_label": "USDT linear perpetual swaps only (PAPER)",
        "global_llm_budget": budget_state,
        "selection_cooldown_remaining_seconds": round(cooldown_remaining_seconds, 1),
        "last_selection": last_selection,
        "market_directory": {
            "pages": directory_pages,
            "note": (
                "read-only factual directory pages; symbols here are outside the "
                "initial candidate pool and may be selected if research-worthy"
            ),
        },
        "authority_note": SELECTION_AUTHORITY_NOTE,
        "output_contract": {
            "selection_state": "SELECTED | NO_RESEARCH",
            "selected_symbols": [
                {
                    "symbol": "string",
                    "brief_reason": "short factual reason",
                    "requested_additional_data": ["optional bounded requests"],
                }
            ],
            "maximum_selected_symbols": MAX_SELECTED_SYMBOLS,
        },
    }


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
        self._last_autonomous_selection_at: datetime | None = None
        self._last_selection_id_by_scan: dict[str, str] = {}
        self._records_by_scan: dict[str, MarketSelectionRecord] = {}
        self.selection_count = 0
        self.last_record: MarketSelectionRecord | None = None

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

        directory_pages: list[dict] = []
        directory_refs: list[str] = []
        if self.directory is not None:
            directory_pages, directory_refs = self.directory.bounded_pages(
                scan_id=snapshot.scan_id, exclude={e.symbol for e in pool}, now=now
            )
        record.directory_query_refs = directory_refs
        context = build_selection_context(
            snapshot=snapshot,
            pool=pool,
            directory_pages=directory_pages,
            existing_positions=list(existing_positions or ()),
            budget_state=budget_state,
            cooldown_remaining_seconds=cooldown_remaining,
            last_selection=self.last_record.as_dict() if self.last_record else None,
            now=now,
        )
        record.candidate_set_ref = f"pool:{snapshot.scan_id}:{len(pool)}"
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

        if ticket:
            ticket.complete(
                status=STATUS_OK if result.ok else "ERROR",
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
                detail=result.error_code,
            )

        if not result.ok:
            record.status = result.status
            record.error_code = result.error_code
            return await self._persist(record, now=now)

        selected = self._materialize(result.output, pool=pool, directory_pages=directory_pages)
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
            for entry in selected:
                self.board.coverage.mark_llm_research(str(entry["symbol"]), now)
                self.board.market_sets.record_research_selected(len(selected))
        self._last_autonomous_selection_at = now
        return await self._persist(record, now=now)

    # -------------------------------------------------------------- internals
    def _materialize(
        self, output: MarketSelectionOutput, *, pool: list[PoolEntry], directory_pages: list[dict]
    ) -> list[dict] | str:
        pool_by_symbol = {entry.symbol: entry for entry in pool}
        directory_symbols = {
            row.get("symbol")
            for page in directory_pages
            for row in (page.get("rows") or ())
        }
        materialized: list[dict] = []
        for item in output.selected_symbols:
            symbol = item.symbol.strip()
            if symbol in pool_by_symbol:
                source = SELECTION_SOURCE_DEEPSEEK
                reasons = list(pool_by_symbol[symbol].reasons)
            elif symbol in directory_symbols:
                # §7.5: discovered through the read-only Market Directory path
                source = SELECTION_SOURCE_DEEPSEEK
                reasons = ["market directory"]
            else:
                return f"SELECTED_SYMBOL_NOT_IN_CONTEXT:{symbol}"[:64]
            materialized.append(
                {
                    "symbol": symbol,
                    "brief_reason": item.brief_reason[:MAX_BRIEF_REASON],
                    "requested_additional_data": list(item.requested_additional_data)[
                        :MAX_REQUESTED_DATA
                    ],
                    "selection_source": source,
                    "pool_reasons": reasons,
                }
            )
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
    elif state in {"SELECTED", "SELECT"}:
        candidate["selection_state"] = STATE_SELECTED
        symbols = candidate.get("selected_symbols")
        if isinstance(symbols, list):
            candidate["selected_symbols"] = [
                {"symbol": s} if isinstance(s, str) else s for s in symbols
            ]
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
    return (
        "You are the Chief Trader selecting WHERE TO SPEND RESEARCH ATTENTION.\n"
        "This is NOT a trade decision. Return JSON only.\n"
        f"{SELECTION_AUTHORITY_NOTE}\n"
        "Decide which 0-3 symbols deserve deeper factual research. Return:\n"
        '{"selection_state":"SELECTED|NO_RESEARCH","selected_symbols":'
        '[{"symbol":"...","brief_reason":"...","requested_additional_data":["..."]}]}\n'
        f"Select at most {MAX_SELECTED_SYMBOLS} symbols. Keep brief_reason short.\n"
        f"MarketSelectionContext: {json.dumps(context, default=str)}"
    )

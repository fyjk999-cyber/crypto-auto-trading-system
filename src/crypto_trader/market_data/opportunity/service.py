"""OpportunityScannerService — the Market Observation Loop (§3.1, Gate 1+2).

Staged design keeps full-market coverage computationally cheap:

    OKX batch tickers      (1 call, whole SWAP universe)
    OKX batch OI           (1 call, timestamped samples for the broad set)
    OKX batch funding      (1 call: instId=ANY&instType, bounded per-instrument
                            fallback for instruments absent from the batch)
        → broad observable facts + eligibility for ALL USDT swaps
    candle-based factors   (bounded-concurrency active set + fair rotation)
        → FactorCandidates (OR admission) inside one immutable snapshot
        → OpportunityBoard (evidence only; ChiefTrader remains the trader)

Hard rules implemented here:

    * provider failure is a FACT (REQUEST_FAILED), never a synthetic zero;
    * future / stale / missing timestamps are distinguished, never clamped;
    * only CLOSED, deduplicated candles feed history, and coverage is reported
      as requested vs actually usable (contiguous tail), never as "120 candles";
    * per-symbol work is bounded by concurrency + per-request timeout + a whole
      scan deadline, so one slow symbol cannot hang the scanner;
    * ``scan_interval_seconds`` is a TARGET CADENCE, not a sleep appended after
      the scan; overruns are marked SCAN_OVERRUN and cycles never overlap.

Authority impact: NONE. This loop observes and nominates; it cannot choose a
direction, create a SignalIntent/TradePlan, size, approve risk or submit orders.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from crypto_trader.market_data.cache import (
    candle_cache_key,
    closed_candle_ttl_seconds,
    get_shared_market_data_cache,
)
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.coverage import (
    CoverageLedger,
    MarketSetCounts,
)
from crypto_trader.market_data.opportunity.eligibility import EligibilityFilter
from crypto_trader.market_data.opportunity.factors import (
    DEFAULT_FACTORS,
    Candle,
    SymbolFacts,
)
from crypto_trader.market_data.opportunity.oi import (
    DEFAULT_OI_WINDOW,
    OiSample,
    OiTimeSeries,
)
from crypto_trader.market_data.opportunity.scanner import FactorScanner, RotationScheduler
from crypto_trader.market_data.opportunity.snapshot import (
    DEFAULT_CANDIDATE_TTL_SECONDS,
    PROVIDER_OKX_PUBLIC,
    SCANNER_VERSION,
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_PARTIAL,
    UNIVERSE_TYPE_OKX_USDT_PERP,
    MarketObservationSnapshot,
    build_data_quality_summary,
    build_feature_coverage,
    new_scan_id,
    snapshot_expiry,
)
from crypto_trader.market_data.opportunity.universe import OkxUniverseManager
from crypto_trader.market_data.quality import (
    ESTIMATED,
    FUTURE_TIMESTAMP,
    MISSING,
    NON_FINITE,
    NOT_SAMPLED,
    REQUEST_FAILED,
    UNSUPPORTED,
    VALID,
    age_seconds,
    build_candle_truth,
)

TICKER_SOURCE = "OKX /api/v5/market/tickers"
OI_SOURCE = "OKX /api/v5/public/open-interests"
FUNDING_SOURCE = "OKX /api/v5/public/funding-rate"
CANDLES_SOURCE = "OKX /api/v5/market/candles"


@dataclass(frozen=True, slots=True)
class ScannerConfig:
    """Stable operational configuration (never live-mutated by learning)."""

    scan_interval_seconds: float = 90.0  # TARGET cadence, not a post-scan sleep
    active_set_size: int = 40
    rotation_size: int = 10
    candle_limit: int = 120
    candle_bar: str = "1m"
    max_concurrency: int = 8
    per_request_timeout_seconds: float = 8.0
    whole_scan_deadline_seconds: float = 120.0
    candidate_ttl_seconds: float = DEFAULT_CANDIDATE_TTL_SECONDS
    ticker_max_age_seconds: float = 120.0
    max_future_skew_seconds: float = 5.0
    funding_fallback_max: int = 25
    min_contiguous_candles: int = 2
    oi_sample_max_symbols: int = 120


@dataclass
class ScanCycleRecord:
    """Factual scheduling record for one cycle (§6.4)."""

    cycle_index: int
    target_start_mono: float
    actual_start_mono: float
    duration_seconds: float
    schedule_drift_seconds: float
    status: str

    def as_dict(self) -> dict:
        return {
            "cycle_index": self.cycle_index,
            "schedule_drift_seconds": round(self.schedule_drift_seconds, 3),
            "duration_seconds": round(self.duration_seconds, 3),
            "status": self.status,
        }


class OpportunityScannerService:
    def __init__(
        self,
        *,
        universe: OkxUniverseManager,
        okx_client,
        board: OpportunityBoard,
        scanner: FactorScanner | None = None,
        eligibility: EligibilityFilter | None = None,
        config: ScannerConfig | None = None,
        # legacy keyword compatibility (pre-V1 call sites)
        scan_interval_seconds: float | None = None,
        active_set_size: int | None = None,
        rotation_size: int | None = None,
        candle_limit: int | None = None,
        candle_bar: str | None = None,
        max_concurrency: int | None = None,
        max_cycles: int | None = None,  # test hook
        sleep=None,
        clock=None,
        coverage: CoverageLedger | None = None,
        market_sets: MarketSetCounts | None = None,
        oi_series: OiTimeSeries | None = None,
        cache=None,
        state_store=None,
        state_save_every_cycles: int = 1,
    ) -> None:
        base = config or ScannerConfig()
        overrides = {
            "scan_interval_seconds": scan_interval_seconds,
            "active_set_size": active_set_size,
            "rotation_size": rotation_size,
            "candle_limit": candle_limit,
            "candle_bar": candle_bar,
            "max_concurrency": max_concurrency,
        }
        resolved = {
            key: (value if value is not None else getattr(base, key))
            for key, value in overrides.items()
        }
        self.config = replace(base, **resolved)
        self.universe = universe
        self.client = okx_client
        self.board = board
        self.scanner = scanner or FactorScanner(factors=DEFAULT_FACTORS)
        self.eligibility = eligibility or EligibilityFilter()
        self.coverage = coverage or CoverageLedger()
        self.market_sets = (
            market_sets
            or getattr(board, "market_sets", None)
            or MarketSetCounts()
        )
        self.oi_series = oi_series or OiTimeSeries()
        # Canonical shared cache: identical market history is never downloaded
        # twice within the (short) freshness window, and failures never poison it.
        self.cache = cache if cache is not None else get_shared_market_data_cache()
        # Restart durability for fairness clocks / rotation / OI samples.
        self.state_store = state_store
        self.state_save_every_cycles = max(1, int(state_save_every_cycles))
        self.state_restored: dict | None = None
        self.max_cycles = max_cycles
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or time.monotonic
        self._rotation = RotationScheduler()
        self.last_error: str | None = None
        self.cycles_completed = 0
        self.scan_overrun_count = 0
        self.last_cycle: ScanCycleRecord | None = None
        self.cycle_history: list[ScanCycleRecord] = []
        self._next_start_mono: float | None = None
        self._scan_lock = asyncio.Lock()

    # ------------------------------------------------------------------- loop
    @property
    def scan_interval_seconds(self) -> float:
        return self.config.scan_interval_seconds

    async def run_forever(self) -> None:
        """Target-cadence loop: no overlapping cycles, SCAN_OVERRUN on overrun.

        Fairness clocks, rotation cursor and OI samples are restored from the
        non-secret settings store so a restart cannot silently re-favour the
        same symbols.
        """
        await self.restore_state()
        cycles = 0
        while self.max_cycles is None or cycles < self.max_cycles:
            if self._next_start_mono is None:
                self._next_start_mono = self._clock()
            target_start = self._next_start_mono
            actual_start = self._clock()
            drift = actual_start - target_start
            try:
                await self.scan_once()
                error = None
            except Exception as exc:  # never kill the runtime over scanning
                error = f"{type(exc).__name__}: {exc}"[:200]
                self.last_error = error
            duration = self._clock() - actual_start
            cycles += 1
            self.cycles_completed = cycles
            overrun = duration > self.config.scan_interval_seconds
            if overrun:
                self.scan_overrun_count += 1
            record = ScanCycleRecord(
                cycle_index=cycles,
                target_start_mono=target_start,
                actual_start_mono=actual_start,
                duration_seconds=duration,
                schedule_drift_seconds=drift,
                status="SCAN_OVERRUN" if overrun else ("SCAN_FAILED" if error else "ON_SCHEDULE"),
            )
            self.last_cycle = record
            self.cycle_history.append(record)
            if len(self.cycle_history) > 50:
                del self.cycle_history[:-50]
            # advance the target grid; never start the next cycle before the
            # previous cycle has safely ended (no overlap by construction).
            self._next_start_mono = target_start + self.config.scan_interval_seconds
            if self._next_start_mono <= self._clock():
                self._next_start_mono = self._clock()
            if self.max_cycles is not None and cycles >= self.max_cycles:
                break  # bounded test hook: no trailing sleep after the last cycle
            delay = max(0.0, self._next_start_mono - self._clock())
            await self._sleep(delay)

    # ------------------------------------------------------------------- scan
    async def scan_once(self) -> dict:
        """Run exactly one observation cycle and publish one immutable snapshot."""
        async with self._scan_lock:  # no overlapping scans, ever
            return await self._scan_once_locked()

    async def _scan_once_locked(self) -> dict:
        started_at = datetime.now(UTC)
        scan_id = new_scan_id()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(1.0, self.config.whole_scan_deadline_seconds)
        summary = await self.universe.refresh()
        instruments = summary.instruments
        discovered_count = summary.size

        try:
            tickers = await asyncio.wait_for(
                self.client.get_tickers("SWAP"),
                timeout=max(
                    0.1,
                    min(self.config.per_request_timeout_seconds, deadline - loop.time()),
                ),
            )
        except Exception as exc:
            self.last_error = f"tickers: {type(exc).__name__}: {exc}"[:200]
            return self._publish_failed_snapshot(
                scan_id=scan_id,
                started_at=started_at,
                discovered_count=discovered_count,
                error=self.last_error,
            )
        if not isinstance(tickers, list) or not tickers:
            self.last_error = "empty OKX tickers batch"
            return self._publish_failed_snapshot(
                scan_id=scan_id,
                started_at=started_at,
                discovered_count=discovered_count,
                error="EMPTY_TICKERS_BATCH",
            )

        funding_rows, funding_quality = await self._batch(
            self.client.get_funding_rates, "SWAP", deadline
        )
        by_inst = {str(r.get("instId")): r for r in tickers if isinstance(r, dict)}
        funding_by_inst = {str(r.get("instId")): r for r in funding_rows if isinstance(r, dict)}
        # Bounded factual fallback for instruments absent from the batch
        # response. Only runs when the batch actually succeeded; a failed batch
        # stays REQUEST_FAILED rather than being silently patched per symbol.
        if funding_quality == VALID:
            missing_inst_ids = [
                inst.inst_id for inst in instruments.values() if inst.inst_id not in funding_by_inst
            ]
            if missing_inst_ids:
                funding_by_inst.update(
                    await self._funding_fallback(missing_inst_ids, deadline=deadline)
                )

        # ---- broad-market facts for the WHOLE universe (cheap) -------------
        facts_rows: list[dict] = []
        ticker_quality_by_symbol: dict[str, str] = {}
        funding_quality_by_symbol: dict[str, str] = {}
        oi_quality_by_symbol: dict[str, str] = {}
        for symbol, inst in instruments.items():
            row = by_inst.get(inst.inst_id)
            if not isinstance(row, dict):
                ticker_quality_by_symbol[symbol] = MISSING
                continue
            observed_at, t_quality, t_reason = self._ticker_timestamp(row, now=started_at)
            last = _finite(row.get("last"))
            open24h = _finite(row.get("open24h"))
            bid, bid_qty = _finite(row.get("bidPx")), _finite(row.get("bidSz"))
            ask, ask_qty = _finite(row.get("askPx")), _finite(row.get("askSz"))
            # OKX SWAP tickers report volume in contracts (vol24h) and base
            # currency (volCcy24h) — there is no exact USD turnover field.
            # Derive a clearly-labelled ESTIMATE: base volume x last price.
            vol_base = _finite(row.get("volCcy24h"))
            vol_contracts = _finite(row.get("vol24h"))
            if vol_base in (None, 0.0) and vol_contracts and inst.ct_val:
                try:
                    vol_base = vol_contracts * float(inst.ct_val)
                except (TypeError, ValueError):
                    vol_base = None
            vol_usd = vol_base * last if (vol_base is not None and last) else None
            change_pct = (
                (last - open24h) / open24h * 100.0 if (last and open24h) else None
            )
            funding_row = funding_by_inst.get(inst.inst_id)
            funding_quality, funding_reason, funding_value = self._funding_fact(
                funding_row, funding_quality
            )
            oi_value = None
            oi_symbol_quality = MISSING
            facts_rows.append(
                {
                    "symbol": symbol,
                    "inst_id": inst.inst_id,
                    "last": last,
                    "open24h": open24h,
                    "bid": bid,
                    "bid_qty": bid_qty,
                    "ask": ask,
                    "ask_qty": ask_qty,
                    "vol_usd_24h": vol_usd,
                    "price_change_24h_pct": change_pct,
                    "funding_rate": funding_value,
                    "funding_quality": funding_quality,
                    "funding_reason": funding_reason,
                    "open_interest": oi_value,
                    "ticker_observed_at": observed_at,
                    "ticker_quality": t_quality,
                    "ticker_reason": t_reason,
                    "ts_ms": row.get("ts"),
                }
            )
            ticker_quality_by_symbol[symbol] = t_quality
            funding_quality_by_symbol[symbol] = funding_quality
            oi_quality_by_symbol[symbol] = oi_symbol_quality

        # ---- bounded factual OI sampling (OKX has no batch endpoint) -------
        oi_quality, oi_quality_by_symbol, oi_collection = await self._collect_open_interest(
            facts_rows, deadline=deadline
        )

        # ---- timestamped OI sampling for the BROAD observable set ----------
        observed_symbols = [r["symbol"] for r in facts_rows]
        for row in facts_rows:
            self.coverage.mark_observed(row["symbol"], started_at)
            if row["open_interest"] is not None and row["open_interest"] > 0:
                self.oi_series.record(
                    OiSample(
                        symbol=row["symbol"],
                        open_interest=float(row["open_interest"]),
                        observed_at=started_at,
                        source=OI_SOURCE,
                    )
                )

        turnover_values = [r["vol_usd_24h"] for r in facts_rows if r["vol_usd_24h"]]
        cohort_median = statistics.median(turnover_values) if turnover_values else None
        self._cohort_median = cohort_median

        # ---- eligibility (operational only; never direction) ---------------
        eligible: list[dict] = []
        for row in facts_rows:
            result = self.eligibility.evaluate(
                row["symbol"],
                last_price=row["last"],
                bid=row["bid"],
                ask=row["ask"],
                volume_24h_usd=row["vol_usd_24h"],
                ticker_age_seconds=self._honest_age(row, now=started_at),
                candle_count=self.config.candle_limit,  # history checked at fetch
                ticker_timestamp_quality=row.get("ticker_quality"),
            )
            row["eligible"] = result.eligible
            row["excluded_reasons"] = result.reasons
            if result.eligible:
                eligible.append(row)
        self._rotation.sync([r["symbol"] for r in eligible])

        # ---- staged candle scan set: most active + fair rotation -----------
        active = sorted(eligible, key=lambda r: -(r["vol_usd_24h"] or 0.0))[
            : self.config.active_set_size
        ]
        candidate_symbols_hint = {r["symbol"] for r in active}
        rotation_symbols = self._rotation.next_batch(
            exclude=candidate_symbols_hint,
            size=self.config.rotation_size,
            ledger=self.coverage,
            now=started_at,
        )
        rotation_set = set(rotation_symbols)
        rotation_by_symbol = {r["symbol"]: r for r in eligible if r["symbol"] in rotation_set}
        scan_rows = active + [
            rotation_by_symbol[s] for s in rotation_symbols if s in rotation_by_symbol
        ]

        # ---- per-symbol factual candles (bounded concurrency + timeout) ----
        facts_by_symbol, candle_quality_by_symbol, candle_stats = await self._collect_candles(
            scan_rows, started_at=started_at, deadline=deadline
        )

        expires_at = snapshot_expiry(started_at, self.config.candidate_ttl_seconds)
        for row in scan_rows:
            symbol = row["symbol"]
            facts = facts_by_symbol.get(symbol)
            if facts is None:
                continue
            facts.oi_samples = self.oi_series.sample_count(symbol)
            oi_change = self.oi_series.window_change(
                symbol, now=started_at, window=DEFAULT_OI_WINDOW
            )
            facts.oi_change_pct = oi_change.value
            facts.oi_change_quality = oi_change.quality
            facts.oi_change_reason = oi_change.reason
            facts.oi_window_changes = {
                label: fact.as_dict()
                for label, fact in self.oi_series.all_window_changes(symbol, now=started_at).items()
            }

        candidates = self.scanner.scan(
            facts_by_symbol,
            scan_id=scan_id,
            created_at=started_at,
            expires_at=expires_at,
        )

        analysis_attempted = len(scan_rows)
        analysis_success = candle_stats["success"]
        analysis_ready = candle_stats["ready"]
        broad_summary = self._broad_summary(facts_rows)
        completed_at = datetime.now(UTC)
        # Execution status describes whether the scan executed its designed
        # plan. Intentional bounded/rotating coverage (e.g. OI that is supported
        # but not collected for every symbol this cycle) is NOT a failure; the
        # coverage ratios are reported separately in feature_coverage.
        status = STATUS_COMPLETE
        notes: list[str] = []
        unexpected_failures: list[str] = []
        if candle_stats["errors"]:
            unexpected_failures.append(f"candle_fetch_errors={candle_stats['errors']}")
        if candle_stats.get("empty_responses"):
            unexpected_failures.append(
                f"candle_empty_responses={candle_stats['empty_responses']}"
            )
        if oi_quality != VALID:
            unexpected_failures.append(f"open_interest_batch={oi_quality}")
        if funding_quality != VALID:
            unexpected_failures.append(f"funding_batch={funding_quality}")
        if unexpected_failures:
            status = STATUS_PARTIAL
            notes.extend(unexpected_failures)
        observable_rows = tuple(
            {
                "symbol": row["symbol"],
                "last": row["last"],
                "price_change_24h_pct": row["price_change_24h_pct"],
                "vol_usd_24h": row["vol_usd_24h"],
                "funding_rate": row["funding_rate"],
                "funding_quality": row["funding_quality"],
                "open_interest": row["open_interest"],
                "open_interest_usd": row.get("open_interest_usd"),
                "oi_quality": oi_quality_by_symbol.get(row["symbol"], NOT_SAMPLED),
                "oi_observed_at": (
                    row["oi_observed_at"].isoformat()
                    if row.get("oi_observed_at")
                    else None
                ),
                "ticker_quality": row["ticker_quality"],
                "ticker_observed_at": (
                    row["ticker_observed_at"].isoformat()
                    if row.get("ticker_observed_at")
                    else None
                ),
                "observed_at": started_at.isoformat(),
                "eligible": row.get("eligible"),
                "excluded_reasons": tuple(row.get("excluded_reasons") or ()),
                # discovery scope is OKX live USDT perpetuals only
                "execution_supported": True,
            }
            for row in facts_rows
        )
        data_quality_summary = build_data_quality_summary(
            funding=funding_quality_by_symbol,
            oi=oi_quality_by_symbol,
            candles=candle_quality_by_symbol,
            total_symbols=discovered_count,
        )
        data_quality_summary.update(
            {
                "batch": {"funding": funding_quality, "open_interest": oi_quality},
                "open_interest_collection": dict(oi_collection),
                "ticker_states": _state_counts(ticker_quality_by_symbol),
                "notes": notes,
                "turnover_semantics": "estimated_quote_turnover_24h (ESTIMATED, derived)",
                "quality_vs_coverage": (
                    "quality states describe fact reliability; coverage ratios "
                    "describe how much of the universe was collected this cycle"
                ),
            }
        )
        feature_coverage = build_feature_coverage(
            discovered_count=discovered_count,
            ticker_quality=ticker_quality_by_symbol,
            funding_quality=funding_quality_by_symbol,
            oi_quality=oi_quality_by_symbol,
            analysis_attempted=analysis_attempted,
            analysis_success=analysis_success,
            analysis_ready=analysis_ready,
        )
        snapshot = MarketObservationSnapshot(
            scan_id=scan_id,
            started_at=started_at,
            completed_at=completed_at,
            expires_at=expires_at,
            status=status,
            provider=PROVIDER_OKX_PUBLIC,
            universe_type=UNIVERSE_TYPE_OKX_USDT_PERP,
            discovered_count=discovered_count,
            observable_count=len(facts_rows),
            analysis_attempted_count=analysis_attempted,
            analysis_success_count=analysis_success,
            analysis_ready_count=analysis_ready,
            execution_supported_count=len(eligible),
            broad_market_summary=broad_summary,
            factor_candidates=tuple(candidates),
            active_symbols=tuple(r["symbol"] for r in active),
            rotation_symbols=tuple(rotation_symbols),
            data_quality_summary=data_quality_summary,
            scanner_version=SCANNER_VERSION,
            observable_rows=observable_rows,
            feature_coverage=feature_coverage,
        )
        self.market_sets.record_scan(
            discovered=discovered_count,
            observable=len(facts_rows),
            attempted=analysis_attempted,
            success=analysis_success,
            ready=analysis_ready,
            execution_supported=len(eligible),
        )
        self.board.publish_snapshot(snapshot)
        self._last_observed_symbols = observed_symbols
        await self._maybe_persist_state()
        return {
            "scan_id": scan_id,
            "status": status,
            "universe_size": discovered_count,
            "eligible": len(eligible),
            "scanned": len(facts_by_symbol),
            "candidates": [c.symbol for c in candidates],
            "rotation": rotation_symbols,
            "market_sets": {
                # explicit sets (never conflated)
                "discovered_count": discovered_count,
                "observable_count": len(facts_rows),
                "analysis_attempted_count": analysis_attempted,
                "analysis_success_count": analysis_success,
                "analysis_ready_count": analysis_ready,
                "execution_supported_count": len(eligible),
                # legacy aliases retained for pre-V1 call sites
                "all_market_count": discovered_count,
                "analysis_count": analysis_attempted,
                "executable_count": len(eligible),
            },
            "candle_coverage": candle_stats,
            "market_data_cache": self.cache.snapshot()["stats"],
            "feature_coverage": feature_coverage,
        }

    # -------------------------------------------------------- restart durability
    def export_state(self) -> dict:
        """Operational scheduling state (never market facts, never authority)."""
        return {
            "version": 1,
            "rotation": self._rotation.export_state(),
            "coverage": self.coverage.export_state(),
            "oi_series": self.oi_series.export_state(),
            "cycles_completed": self.cycles_completed,
            "scan_overrun_count": self.scan_overrun_count,
        }

    async def restore_state(self) -> int:
        """Restore fairness clocks / rotation cursor / OI samples after restart."""
        if self.state_store is None:
            return 0
        payload = await self.state_store.load()
        if not payload:
            return 0
        restored = 0
        if self._rotation.import_state(payload.get("rotation")):
            restored += 1
        restored += self.coverage.import_state(payload.get("coverage"))
        restored += self.oi_series.import_state(payload.get("oi_series"))
        self.cycles_completed = int(payload.get("cycles_completed") or 0)
        self.scan_overrun_count = int(payload.get("scan_overrun_count") or 0)
        self.state_restored = payload
        return restored

    async def _maybe_persist_state(self) -> None:
        if self.state_store is None:
            return
        if self.cycles_completed and self.cycles_completed % self.state_save_every_cycles != 0:
            return
        try:
            await self.state_store.save(self.export_state())
        except Exception:  # persistence is best-effort, never fatal
            self.last_error = "SCANNER_STATE_PERSIST_FAILED"

    # -------------------------------------------------------------- internals
    async def _batch(self, method, inst_type: str, deadline: float) -> tuple[list[dict], str]:
        """Factual batch call: provider failure returns quality REQUEST_FAILED."""
        loop = asyncio.get_running_loop()
        remaining = deadline - loop.time()
        if remaining <= 0:
            return [], REQUEST_FAILED
        try:
            rows = await asyncio.wait_for(
                method(inst_type),
                timeout=max(0.1, min(self.config.per_request_timeout_seconds, remaining)),
            )
        except Exception as exc:
            self.last_error = f"{getattr(method, '__name__', 'batch')}: {type(exc).__name__}"
            return [], REQUEST_FAILED
        if not isinstance(rows, list):
            self.last_error = f"{getattr(method, '__name__', 'batch')}: malformed response"
            return [], REQUEST_FAILED
        if not rows:
            return [], MISSING
        return rows, VALID

    async def _collect_open_interest(
        self, facts_rows: list[dict], *, deadline: float
    ) -> tuple[str, dict[str, str], dict[str, int]]:
        """Broad factual OI collection with a bounded per-instrument fallback.

        OKX DOES support broad open interest: ``GET /api/v5/public/open-interest
        ?instType=SWAP`` (no ``instId``) returns one row per instrument with
        ``oi`` (contracts), ``oiCcy``, ``oiUsd`` and ``ts`` — live-verified at
        478 rows / 463 USDT perpetuals, which is the whole discovery universe.

        Therefore the broad response is the PRIMARY source (one request), not a
        120-symbol rotation. Per-instrument requests are used only as a bounded
        fallback for instruments absent from a successful broad response, and
        symbols still missing are reported ``NOT_SAMPLED`` (supported but not
        collected) — never ``UNSUPPORTED``, which would misstate provider
        capability.
        """
        quality_by_symbol: dict[str, str] = {}
        rows_by_symbol = {row["symbol"]: row for row in facts_rows}
        fetched_at = datetime.now(UTC)
        batch = getattr(self.client, "get_open_interests", None)
        if not callable(batch):
            for symbol in rows_by_symbol:
                quality_by_symbol[symbol] = UNSUPPORTED
            return (
                UNSUPPORTED,
                quality_by_symbol,
                {"requested": len(rows_by_symbol), "collected": 0},
            )
        rows, batch_quality = await self._batch(batch, "SWAP", deadline)
        if batch_quality != VALID:
            # an unexpected provider failure: every symbol is REQUEST_FAILED,
            # which the snapshot status reports as PARTIAL
            for symbol in rows_by_symbol:
                rows_by_symbol[symbol]["oi_quality"] = batch_quality
            quality_by_symbol = {symbol: batch_quality for symbol in rows_by_symbol}
            return batch_quality, quality_by_symbol, {
                "requested": len(rows_by_symbol),
                "collected": 0,
            }

        by_inst = {str(r.get("instId")): r for r in rows if isinstance(r, dict)}
        collected = 0
        missing_inst_ids: list[str] = []
        for symbol, row in rows_by_symbol.items():
            oi_row = by_inst.get(row["inst_id"])
            if not isinstance(oi_row, dict):
                missing_inst_ids.append(row["inst_id"])
                continue
            value = _finite(oi_row.get("oi"))
            if value is None:
                quality_by_symbol[symbol] = NON_FINITE if oi_row.get("oi") else MISSING
                continue
            if value < 0:
                quality_by_symbol[symbol] = MISSING
                continue
            observed_at, ts_quality, _reason = self._ticker_timestamp(
                {"ts": oi_row.get("ts")}, now=fetched_at
            )
            if ts_quality not in (VALID, MISSING):
                # the value exists but its observation time is unusable: never
                # present it as a fresh fact
                quality_by_symbol[symbol] = ts_quality
                continue
            row["open_interest"] = float(value)
            row["open_interest_usd"] = _finite(oi_row.get("oiUsd"))
            row["oi_observed_at"] = observed_at or fetched_at
            row["oi_quality"] = VALID
            quality_by_symbol[symbol] = VALID
            collected += 1

        # bounded factual fallback for instruments absent from a SUCCESSFUL
        # broad response (provider coverage gaps, newly listed instruments)
        fallback_cap = max(0, int(self.config.oi_sample_max_symbols))
        if missing_inst_ids and fallback_cap:
            fallback_rows = await self._open_interest_fallback(
                missing_inst_ids[:fallback_cap], deadline=deadline, now=fetched_at
            )
            for symbol, row in rows_by_symbol.items():
                if row["inst_id"] not in fallback_rows:
                    continue
                payload = fallback_rows[row["inst_id"]]
                value = _finite(payload.get("open_interest"))
                if value is None or value < 0:
                    quality_by_symbol[symbol] = MISSING
                    continue
                row["open_interest"] = float(value)
                row["open_interest_usd"] = _finite(payload.get("open_interest_usd"))
                row["oi_observed_at"] = fetched_at
                row["oi_quality"] = VALID
                quality_by_symbol[symbol] = VALID
                collected += 1

        for symbol in rows_by_symbol:
            quality_by_symbol.setdefault(symbol, NOT_SAMPLED)
        return VALID, quality_by_symbol, {
            "requested": len(rows_by_symbol),
            "collected": collected,
        }

    async def _open_interest_fallback(
        self, inst_ids: list[str], *, deadline: float, now: datetime
    ) -> dict[str, dict]:
        """Bounded per-instrument OI lookups (fallback only, small cap)."""
        fetcher = getattr(self.client, "get_open_interest", None)
        if not callable(fetcher):
            return {}
        loop = asyncio.get_running_loop()
        semaphore = asyncio.Semaphore(max(1, self.config.max_concurrency))
        results: dict[str, dict] = {}

        async def fetch(inst_id: str) -> tuple[str, dict | None]:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return inst_id, None
            async with semaphore:
                try:
                    payload = await asyncio.wait_for(
                        fetcher(inst_id),
                        timeout=max(
                            0.1, min(self.config.per_request_timeout_seconds, remaining)
                        ),
                    )
                except Exception:
                    return inst_id, None
            return inst_id, payload if isinstance(payload, dict) else None

        for inst_id, payload in await asyncio.gather(*(fetch(i) for i in inst_ids)):
            if payload is not None:
                results[inst_id] = payload
        return results

    async def _funding_fallback(
        self, inst_ids: list[str], *, deadline: float
    ) -> dict[str, dict]:
        """Bounded per-instrument fallback for instruments missing from batch."""
        loop = asyncio.get_running_loop()
        results: dict[str, dict] = {}
        if not inst_ids or self.config.funding_fallback_max <= 0:
            return results
        fallback = getattr(self.client, "get_funding_rate_fallback", None)
        if fallback is None:
            return results
        semaphore = asyncio.Semaphore(max(1, self.config.max_concurrency))

        async def fetch(inst_id: str) -> tuple[str, dict | None]:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return inst_id, None
            async with semaphore:
                try:
                    row = await asyncio.wait_for(
                        fallback(inst_id),
                        timeout=max(
                            0.1, min(self.config.per_request_timeout_seconds, remaining)
                        ),
                    )
                except Exception:
                    return inst_id, None
            return inst_id, row if isinstance(row, dict) else None

        bounded = inst_ids[: self.config.funding_fallback_max]
        for inst_id, row in await asyncio.gather(*(fetch(i) for i in bounded)):
            if row is not None:
                results[inst_id] = row
        return results

    async def _collect_candles(
        self, scan_rows: list[dict], *, started_at: datetime, deadline: float
    ) -> tuple[dict[str, SymbolFacts], dict[str, str], dict]:
        """Bounded-concurrency candle fetch with per-request timeout + deadline."""
        facts_by_symbol: dict[str, SymbolFacts] = {}
        candle_quality: dict[str, str] = {}
        semaphore = asyncio.Semaphore(max(1, self.config.max_concurrency))
        loop = asyncio.get_running_loop()
        errors = 0
        empty_responses = 0
        ready = 0
        success = 0
        gap_total = 0

        async def fetch(row: dict) -> dict:
            symbol = row["symbol"]
            remaining = deadline - loop.time()
            if remaining <= 0:
                return {"symbol": symbol, "candles": [], "quality": REQUEST_FAILED, "truth": {}}
            async with semaphore:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return {
                        "symbol": symbol,
                        "candles": [],
                        "quality": REQUEST_FAILED,
                        "truth": {},
                    }
                failure: dict = {"kind": None}

                async def _loader():
                    try:
                        return await asyncio.wait_for(
                            self.client.get_candles(
                                row["inst_id"],
                                self.config.candle_bar,
                                self.config.candle_limit,
                            ),
                            timeout=max(
                                0.1,
                                min(self.config.per_request_timeout_seconds, remaining),
                            ),
                        )
                    except TimeoutError:
                        failure["kind"] = "TIMEOUT"
                        raise
                    except Exception:
                        failure["kind"] = "REQUEST_FAILED"
                        raise

                try:
                    rows, cache_quality, cache_hit = await self.cache.get_or_fetch(
                        candle_cache_key(
                            instrument=row["inst_id"],
                            timeframe=self.config.candle_bar,
                            limit=self.config.candle_limit,
                        ),
                        _loader,
                        ttl_seconds=closed_candle_ttl_seconds(
                            _bar_seconds(self.config.candle_bar)
                        ),
                        source=CANDLES_SOURCE,
                        is_usable=lambda payload: isinstance(payload, list) and bool(payload),
                    )
                    if cache_quality != VALID or rows is None:
                        # distinguish a provider failure from a 200-with-empty-body:
                        # both are unusable, but only one is an error
                        kind = failure["kind"] or (
                            "EMPTY" if cache_quality == MISSING else "REQUEST_FAILED"
                        )
                        return {
                            "symbol": symbol,
                            "candles": [],
                            "quality": REQUEST_FAILED if kind != "EMPTY" else MISSING,
                            "truth": {},
                            "error": kind,
                            "cache_hit": cache_hit,
                        }
                except TimeoutError:
                    return {
                        "symbol": symbol,
                        "candles": [],
                        "quality": REQUEST_FAILED,
                        "truth": {},
                        "error": "TIMEOUT",
                    }
                except Exception:
                    return {
                        "symbol": symbol,
                        "candles": [],
                        "quality": REQUEST_FAILED,
                        "truth": {},
                        "error": "REQUEST_FAILED",
                    }
            closed_rows, truth = build_candle_truth(
                requested_count=self.config.candle_limit,
                rows=rows if isinstance(rows, list) else [],
                bar_seconds=_bar_seconds(self.config.candle_bar),
                now=started_at,
                max_future_skew_seconds=self.config.max_future_skew_seconds,
            )
            candles: list[Candle] = []
            for ts_ms, raw in closed_rows:
                try:
                    candles.append(
                        Candle(
                            ts_ms=ts_ms,
                            open=float(raw[1]),
                            high=float(raw[2]),
                            low=float(raw[3]),
                            close=float(raw[4]),
                            volume=float(raw[5]),
                        )
                    )
                except (TypeError, ValueError, IndexError):
                    continue
            return {
                "symbol": symbol,
                "candles": candles,
                "quality": truth.quality,
                "truth": truth.as_dict(),
                "cache_hit": locals().get("cache_hit", False),
            }

        results = await asyncio.gather(*(fetch(row) for row in scan_rows))
        for row, result in zip(scan_rows, results, strict=True):
            symbol = row["symbol"]
            candles = result["candles"]
            truth = result.get("truth") or {}
            if result.get("error") == "EMPTY":
                empty_responses += 1
            elif result.get("error"):
                errors += 1
            if candles:
                success += 1
            contiguous = int(truth.get("contiguous_tail_count") or 0)
            gap_total += int(truth.get("gap_count") or 0)
            if contiguous >= self.config.min_contiguous_candles:
                ready += 1
            self.coverage.mark_analysis_attempt(
                symbol, started_at, success=bool(candles)
            )
            candle_quality[symbol] = result["quality"]
            facts_by_symbol[symbol] = SymbolFacts(
                symbol=symbol,
                candles=candles,
                last_price=row["last"],
                bid=row["bid"],
                ask=row["ask"],
                bid_qty=row.get("bid_qty"),
                ask_qty=row.get("ask_qty"),
                volume_24h_usd=row["vol_usd_24h"],
                price_change_24h_pct=row["price_change_24h_pct"],
                funding_rate=row["funding_rate"],
                funding_quality=row["funding_quality"],
                funding_reason=row["funding_reason"],
                open_interest=row["open_interest"],
                cohort_median_turnover_usd=self._cohort_median,
                observed_at=started_at,
                ticker_observed_at=row.get("ticker_observed_at"),
                oi_observed_at=started_at,
                candles_observed_at=started_at if candles else None,
                ticker_quality=row.get("ticker_quality", MISSING),
                ticker_reason=row.get("ticker_reason"),
                turnover_quality=ESTIMATED if row["vol_usd_24h"] is not None else MISSING,
                turnover_source="derived: OKX volCcy24h x last price",
                candle_quality=result["quality"],
                candle_reason=truth.get("reason"),
                candle_truth=truth,
            )
        return (
            facts_by_symbol,
            candle_quality,
            {
                "attempted": len(scan_rows),
                "success": success,
                "ready": ready,
                "errors": errors,
                "empty_responses": empty_responses,
                "gap_count": gap_total,
                "min_contiguous_candles": self.config.min_contiguous_candles,
            },
        )

    def _ticker_timestamp(
        self, row: dict, *, now: datetime
    ) -> tuple[datetime | None, str, str | None]:
        raw = row.get("ts")
        if raw is None or raw == "":
            return None, MISSING, "ticker timestamp absent"
        try:
            ts = float(raw)
        except (TypeError, ValueError):
            return None, NON_FINITE, "ticker timestamp malformed"
        from crypto_trader.market_data.quality import timestamp_fact

        return timestamp_fact(
            ts,
            now=now,
            source=TICKER_SOURCE,
            max_age_seconds=self.config.ticker_max_age_seconds,
            max_future_skew_seconds=self.config.max_future_skew_seconds,
        )

    @staticmethod
    def _honest_age(row: dict, *, now: datetime) -> float | None:
        """Ticker age used for eligibility. Future timestamps are NOT clamped
        to zero: they are refused as a freshness proof (see ticker_quality)."""
        observed = row.get("ticker_observed_at")
        quality = row.get("ticker_quality")
        if observed is None or quality in (MISSING, FUTURE_TIMESTAMP, NON_FINITE):
            return None
        return age_seconds(observed, now=now)

    @staticmethod
    def _funding_fact(row: dict | None, batch_quality: str) -> tuple[str, str | None, float | None]:
        """Classify one funding fact.

        Distinguishes VALID funding == 0 from MISSING / REQUEST_FAILED /
        UNSUPPORTED. A provider failure never renders as zero funding.
        """
        if batch_quality != VALID:
            return batch_quality, f"batch funding request state={batch_quality}", None
        if not isinstance(row, dict):
            return MISSING, "instrument absent from funding batch", None
        raw = row.get("fundingRate")
        if raw is None or raw == "":
            return MISSING, "fundingRate absent in batch row", None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return NON_FINITE, "fundingRate malformed", None
        if value != value or value in (float("inf"), float("-inf")):
            return NON_FINITE, "fundingRate non-finite", None
        return VALID, None, value

    def _publish_failed_snapshot(
        self,
        *,
        scan_id: str,
        started_at: datetime,
        discovered_count: int,
        error: str,
    ) -> dict:
        """A failed scan publishes FAILED with zero candidates.

        It must never make an old board look fresh: the snapshot carries the new
        (failed) scan_id and no candidates, and autonomous selection refuses it.
        """
        completed_at = datetime.now(UTC)
        snapshot = MarketObservationSnapshot(
            scan_id=scan_id,
            started_at=started_at,
            completed_at=completed_at,
            expires_at=snapshot_expiry(started_at, self.config.candidate_ttl_seconds),
            status=STATUS_FAILED,
            discovered_count=discovered_count,
            broad_market_summary={},
            factor_candidates=(),
            data_quality_summary={"error": error},
            scanner_version=SCANNER_VERSION,
            error=error,
        )
        self.board.publish_snapshot(snapshot)
        return {
            "scan_id": scan_id,
            "status": STATUS_FAILED,
            "universe_size": discovered_count,
            "eligible": 0,
            "scanned": 0,
            "candidates": [],
            "rotation": [],
            "error": error,
            "market_sets": {
                "discovered_count": discovered_count,
                "observable_count": 0,
                "analysis_attempted_count": 0,
                "analysis_success_count": 0,
                "analysis_ready_count": 0,
                "execution_supported_count": 0,
                "all_market_count": discovered_count,
                "analysis_count": 0,
                "executable_count": 0,
            },
        }

    @staticmethod
    def _broad_summary(facts_rows: list[dict], top: int = 8) -> dict:
        """Cheap factual broad-market context (no direction labels)."""
        movers = sorted(
            (r for r in facts_rows if r["price_change_24h_pct"] is not None and r["vol_usd_24h"]),
            key=lambda r: -abs(r["price_change_24h_pct"]),
        )[:top]
        return {
            "rows_observed": len(facts_rows),
            "top_abs_movers_24h": [
                {
                    "symbol": r["symbol"],
                    "price_change_24h_pct": round(r["price_change_24h_pct"], 3),
                    "estimated_quote_turnover_24h": round(r["vol_usd_24h"] or 0.0, 0),
                    "turnover_quality": "ESTIMATED",
                }
                for r in movers
            ],
            "note": (
                "broad market context is factual observation only; it neither "
                "grants nor denies any symbol the possibility of ChiefTrader review"
            ),
        }

    # populated per cycle (bounded, factual)
    _cohort_median: float | None = None
    _last_observed_symbols: list[str] | None = None


def _bar_seconds(bar: str) -> float:
    mapping = {
        "1m": 60.0,
        "3m": 180.0,
        "5m": 300.0,
        "15m": 900.0,
        "30m": 1800.0,
        "1H": 3600.0,
        "1h": 3600.0,
        "2H": 7200.0,
        "4H": 14400.0,
    }
    return mapping.get(str(bar), 60.0)


def _finite(value) -> float | None:
    """Numeric integrity: reject NaN / Infinity / malformed values outright."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _state_counts(states: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for state in states.values():
        counts[state] = counts.get(state, 0) + 1
    return counts

"""OpportunityScannerService — periodic staged full-market scan (§11/§24/§25).

Staged design keeps full-market coverage computationally cheap:

    OKX batch tickers      (1 call, whole SWAP universe)
    OKX batch OI           (1 call)
    OKX batch funding      (1 call)
        → broad-market facts + eligibility for ALL USDT swaps
    candle-based factors   (bounded active set + rotation slice, per symbol)
        → FactorCandidates (OR admission) + rotation queue
        → OpportunityBoard (evidence only; DeepSeek remains the trader)

The service never trades, never gates, and never emits direction. Provider
failures degrade the cycle (fewer facts) instead of crashing the runtime;
an entirely failed ticker batch skips the cycle (fail-safe, no synthetic
substitute — §8).
"""

from __future__ import annotations

import asyncio
import statistics
from datetime import UTC, datetime

from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.eligibility import EligibilityFilter
from crypto_trader.market_data.opportunity.factors import (
    DEFAULT_FACTORS,
    Candle,
    SymbolFacts,
)
from crypto_trader.market_data.opportunity.scanner import FactorScanner, RotationScheduler
from crypto_trader.market_data.opportunity.universe import OkxUniverseManager

_OI_HISTORY_MAX = 8


class OpportunityScannerService:
    def __init__(
        self,
        *,
        universe: OkxUniverseManager,
        okx_client,
        board: OpportunityBoard,
        scanner: FactorScanner | None = None,
        eligibility: EligibilityFilter | None = None,
        scan_interval_seconds: float = 90.0,
        active_set_size: int = 40,
        rotation_size: int = 10,
        candle_limit: int = 120,
        candle_bar: str = "1m",
        max_cycles: int | None = None,  # test hook
        sleep=None,
    ) -> None:
        self.universe = universe
        self.client = okx_client
        self.board = board
        self.scanner = scanner or FactorScanner(factors=DEFAULT_FACTORS)
        self.eligibility = eligibility or EligibilityFilter()
        self.scan_interval_seconds = float(scan_interval_seconds)
        self.active_set_size = int(active_set_size)
        self.rotation_size = int(rotation_size)
        self.candle_limit = int(candle_limit)
        self.candle_bar = candle_bar
        self.max_cycles = max_cycles
        self._sleep = sleep or asyncio.sleep
        self._rotation = RotationScheduler()
        self._oi_history: dict[str, list[float]] = {}
        self.last_error: str | None = None
        self.cycles_completed = 0

    # ------------------------------------------------------------------- loop
    async def run_forever(self) -> None:
        cycles = 0
        while self.max_cycles is None or cycles < self.max_cycles:
            try:
                await self.scan_once()
            except Exception as exc:  # never kill the runtime over scanning
                self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            cycles += 1
            self.cycles_completed = cycles
            await self._sleep(self.scan_interval_seconds)

    # ------------------------------------------------------------------- scan
    async def scan_once(self) -> dict:
        snapshot = await self.universe.refresh()
        instruments = snapshot.instruments
        now = datetime.now(UTC)

        tickers = await self.client.get_tickers("SWAP")
        if not isinstance(tickers, list) or not tickers:
            raise RuntimeError("empty OKX tickers batch")
        by_inst = {str(r.get("instId")): r for r in tickers if isinstance(r, dict)}
        oi_rows = await self._safe_batch(self.client.get_open_interests, "SWAP")
        funding_rows = await self._safe_batch(self.client.get_funding_rates, "SWAP")
        oi_by_inst = {str(r.get("instId")): r for r in oi_rows if isinstance(r, dict)}
        funding_by_inst = {str(r.get("instId")): r for r in funding_rows if isinstance(r, dict)}

        # ---- broad-market facts for the WHOLE universe (cheap) -------------
        facts_rows: list[dict] = []
        for symbol, inst in instruments.items():
            row = by_inst.get(inst.inst_id)
            if not isinstance(row, dict):
                continue
            last = _f(row.get("last"))
            open24h = _f(row.get("open24h"))
            vol_usd = _f(row.get("volUsd24h"))
            bid, ask = _f(row.get("bidPx")), _f(row.get("askPx"))
            funding = _f((funding_by_inst.get(inst.inst_id) or {}).get("fundingRate"))
            oi = _f((oi_by_inst.get(inst.inst_id) or {}).get("oi"))
            change_pct = (last - open24h) / open24h * 100.0 if last and open24h else None
            facts_rows.append(
                {
                    "symbol": symbol,
                    "inst_id": inst.inst_id,
                    "last": last,
                    "open24h": open24h,
                    "bid": bid,
                    "ask": ask,
                    "vol_usd_24h": vol_usd,
                    "price_change_24h_pct": change_pct,
                    "funding_rate": funding,
                    "open_interest": oi,
                    "ts_ms": row.get("ts"),
                }
            )

        turnover_values = [r["vol_usd_24h"] for r in facts_rows if r["vol_usd_24h"]]
        cohort_median = statistics.median(turnover_values) if turnover_values else None

        # ---- eligibility (operational only; never direction) ---------------
        eligible: list[dict] = []
        for row in facts_rows:
            result = self.eligibility.evaluate(
                row["symbol"],
                last_price=row["last"],
                bid=row["bid"],
                ask=row["ask"],
                volume_24h_usd=row["vol_usd_24h"],
                ticker_age_seconds=None,
                candle_count=self.candle_limit,  # history presence checked at fetch
            )
            row["eligible"] = result.eligible
            row["excluded_reasons"] = result.reasons
            if result.eligible:
                eligible.append(row)
        self._rotation.sync([r["symbol"] for r in eligible])

        # ---- staged candle scan set: most active + rotation slice ----------
        active = sorted(
            eligible,
            key=lambda r: -(r["vol_usd_24h"] or 0.0),
        )[: self.active_set_size]
        candidate_symbols_hint = {r["symbol"] for r in active}
        rotation_rows = [
            r
            for r in self._rotation.next_batch(
                exclude=candidate_symbols_hint, size=self.rotation_size
            )
        ]
        rotation_by_symbol = {r["symbol"]: r for r in eligible if r["symbol"] in set(rotation_rows)}
        scan_rows = active + [
            rotation_by_symbol[s] for s in rotation_rows if s in rotation_by_symbol
        ]

        # ---- per-symbol factual candles + factor scan -----------------------
        facts_by_symbol: dict[str, SymbolFacts] = {}
        candle_fetch_errors = 0
        for row in scan_rows:
            candles = await self._fetch_candles(row["inst_id"])
            if candles is None:
                candle_fetch_errors += 1
                candles = []
            oi_change, oi_samples = self._record_oi(row["symbol"], row["open_interest"])
            facts_by_symbol[row["symbol"]] = SymbolFacts(
                symbol=row["symbol"],
                candles=candles,
                last_price=row["last"],
                bid=row["bid"],
                ask=row["ask"],
                volume_24h_usd=row["vol_usd_24h"],
                price_change_24h_pct=row["price_change_24h_pct"],
                funding_rate=row["funding_rate"],
                open_interest=row["open_interest"],
                oi_change_pct=oi_change,
                oi_samples=oi_samples,
                cohort_median_turnover_usd=cohort_median,
                observed_at=now,
            )

        candidates = self.scanner.scan(facts_by_symbol)

        broad_summary = self._broad_summary(facts_rows)
        self.board.publish(
            candidates=candidates,
            broad_market=broad_summary,
            scan_stats={
                **self.scanner.stats.as_dict(),
                "scan_set_size": len(scan_rows),
                "candle_fetch_errors": candle_fetch_errors,
                "universe_rows_with_ticker": len(facts_rows),
            },
            universe_size=snapshot.size,
            eligible_count=len(eligible),
            rotation_symbols=rotation_rows,
        )
        self.cycles_completed += 0  # maintained by run_forever
        return {
            "universe_size": snapshot.size,
            "eligible": len(eligible),
            "scanned": len(facts_by_symbol),
            "candidates": [c.symbol for c in candidates],
            "rotation": rotation_rows,
        }

    # -------------------------------------------------------------- internals
    async def _safe_batch(self, method, inst_type: str) -> list[dict]:
        try:
            rows = await method(inst_type)
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    async def _fetch_candles(self, inst_id: str) -> list[Candle] | None:
        try:
            rows = await self.client.get_candles(inst_id, self.candle_bar, self.candle_limit)
        except Exception:
            return None
        candles: list[Candle] = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 9:
                continue
            if str(row[8]) != "1":  # only factual CLOSED candles (§27)
                continue
            try:
                candles.append(
                    Candle(
                        ts_ms=int(row[0]),
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                    )
                )
            except (TypeError, ValueError):
                continue
        candles.sort(key=lambda c: c.ts_ms)  # ascending for detectors
        return candles

    def _record_oi(self, symbol: str, oi: float | None) -> tuple[float | None, int]:
        if oi is None or oi <= 0:
            hist = self._oi_history.get(symbol, [])
            return None, len(hist)
        hist = self._oi_history.setdefault(symbol, [])
        hist.append(oi)
        if len(hist) > _OI_HISTORY_MAX:
            del hist[:-_OI_HISTORY_MAX]
        if len(hist) < 2:
            return None, len(hist)
        base = hist[0]
        change = (hist[-1] - base) / base * 100.0 if base else None
        return change, len(hist)

    @staticmethod
    def _broad_summary(facts_rows: list[dict], top: int = 8) -> dict:
        """Cheap factual broad-market context (no direction labels, §11)."""
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
                    "volume_24h_usd": round(r["vol_usd_24h"] or 0.0, 0),
                }
                for r in movers
            ],
            "note": (
                "broad market context is factual observation only; it neither "
                "grants nor denies any symbol the possibility of DeepSeek review"
            ),
        }


def _f(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
